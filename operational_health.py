#!/usr/bin/env python3
"""
Operational health for the long-running bot process.

`/healthz` only proves that the HTTP listener is alive.  This module answers
the more useful question: did the trading loop recently evaluate markets, is
the primary data store healthy, and why are entries not being recorded?
"""

import os
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

from decision_log import load_decisions, summarize_decisions, trade_execution_summary


STALE_DECISION_SECONDS = 2 * 60 * 60


def _github_persistence_primary() -> bool:
    return os.environ.get("PERSISTENCE_MODE", "github").strip().lower() in {
        "github",
        "github_primary",
        "free",
    }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _age_seconds(dt: Optional[datetime], now: datetime) -> Optional[int]:
    if not dt:
        return None
    return max(0, int((now - dt).total_seconds()))


def _latest_history_ts(history: Iterable[Dict[str, Any]], *fields: str) -> Optional[datetime]:
    latest = None
    for trade in history or []:
        if not isinstance(trade, dict):
            continue
        for field in fields:
            dt = _parse_ts(trade.get(field))
            if dt and (latest is None or dt > latest):
                latest = dt
    return latest


def build_operational_health(
    data: Optional[Dict[str, Any]],
    data_warning: Optional[str] = None,
    *,
    decision_events: Optional[Iterable[Dict[str, Any]]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    now = (now or _now()).astimezone(timezone.utc)
    data = data if isinstance(data, dict) else {}
    history = data.get("history", []) if isinstance(data.get("history", []), list) else []

    decisions = list(decision_events) if decision_events is not None else load_decisions(limit=500)
    decision_summary = summarize_decisions(decisions)
    last_decision_dt = _parse_ts(decision_summary.get("last_ts"))
    last_trade_decision_dt = _parse_ts(decision_summary.get("last_trade_ts"))
    last_entry_dt = _latest_history_ts(history, "entry_time")
    last_exit_dt = _latest_history_ts(history, "exit_time")
    last_saved_dt = _parse_ts(data.get("saved_at"))

    reason_counts = decision_summary.get("by_reason", {})
    dominant_reason = None
    if reason_counts:
        dominant_reason = max(reason_counts.items(), key=lambda item: item[1])[0]

    open_count = sum(1 for t in history if isinstance(t, dict) and t.get("result") == "OPEN")
    execution = trade_execution_summary(history)
    github_primary = _github_persistence_primary()
    if github_primary:
        data_source = "github"
        db_ok = not bool(data_warning)
    else:
        data_source = "github_fallback" if data_warning else "postgresql"
        db_ok = not bool(data_warning)

    last_decision_age = _age_seconds(last_decision_dt, now)
    stale = last_decision_age is None or last_decision_age > STALE_DECISION_SECONDS

    if not decisions:
        status = "unknown"
        summary = "sem decision_log recente"
    elif stale:
        status = "stale"
        summary = "loop sem decisoes recentes"
    elif not db_ok:
        status = "degraded"
        summary = "loop ativo, mas armazenamento indisponivel" if github_primary else "loop ativo, mas PostgreSQL indisponivel"
    elif decision_summary.get("recorded_count", 0) == 0 and decision_summary.get("signal_count", 0) == 0:
        status = "ok_no_entries"
        summary = "loop ativo, entradas bloqueadas pelos guardrails"
    else:
        status = "ok"
        summary = "loop ativo"

    return {
        "status": status,
        "summary": summary,
        "generated_at": _iso(now),
        "data_source": data_source,
        "db_ok": db_ok,
        "data_warning": data_warning,
        "bot_active": bool(decisions and not stale),
        "stale_after_seconds": STALE_DECISION_SECONDS,
        "last_decision_ts": _iso(last_decision_dt),
        "last_decision_age_seconds": last_decision_age,
        "last_trade_decision_ts": _iso(last_trade_decision_dt),
        "last_entry_ts": _iso(last_entry_dt),
        "last_exit_ts": _iso(last_exit_dt),
        "last_bankroll_saved_at": _iso(last_saved_dt),
        "open_count": open_count,
        "balance": data.get("balance"),
        "seq": data.get("seq"),
        "dominant_block_reason": dominant_reason,
        "decision_counts": {
            "total": decision_summary.get("total", 0),
            "blocked": decision_summary.get("blocked_count", 0),
            "recorded": decision_summary.get("recorded_count", 0),
            "signal": decision_summary.get("signal_count", 0),
            "error": decision_summary.get("error_count", 0),
            "by_reason": reason_counts,
        },
        "execution": execution,
    }


def _metric_value(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if value is None:
        return "0"
    try:
        return str(float(value))
    except Exception:
        return "0"


def _label_value(value: Any) -> str:
    text = str(value or "")
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def _gauge(name: str, help_text: str, value: Any, labels: Optional[Dict[str, Any]] = None) -> list:
    label_text = ""
    if labels:
        parts = [f'{k}="{_label_value(v)}"' for k, v in sorted(labels.items())]
        label_text = "{" + ",".join(parts) + "}"
    return [
        f"# HELP {name} {help_text}",
        f"# TYPE {name} gauge",
        f"{name}{label_text} {_metric_value(value)}",
    ]


def build_prometheus_metrics(health: Dict[str, Any]) -> str:
    """
    Render a compact Prometheus exposition from build_operational_health().
    """
    decisions = health.get("decision_counts", {}) if isinstance(health, dict) else {}
    execution = health.get("execution", {}) if isinstance(health, dict) else {}
    status = health.get("status", "unknown")
    dominant = health.get("dominant_block_reason") or "none"

    lines = []
    lines += _gauge("bot_health_status", "1 for the current bot health status label.", 1, {"status": status})
    lines += _gauge("bot_active", "1 when the trading loop has recent decision telemetry.", health.get("bot_active"))
    lines += _gauge("bot_db_ok", "1 when PostgreSQL is the current data source.", health.get("db_ok"))
    lines += _gauge(
        "bot_last_decision_age_seconds",
        "Age in seconds of the latest decision-log event.",
        health.get("last_decision_age_seconds"),
    )
    lines += _gauge("bot_open_trades", "Number of currently open trades.", health.get("open_count"))
    lines += _gauge("bot_balance", "Current bankroll balance.", health.get("balance"))
    lines += _gauge("bot_decisions_total", "Recent decision-log events.", decisions.get("total", 0))
    lines += _gauge("bot_decisions_blocked", "Recent blocked decisions.", decisions.get("blocked", 0))
    lines += _gauge("bot_decisions_recorded", "Recent recorded trades.", decisions.get("recorded", 0))
    lines += _gauge("bot_decisions_signal", "Recent signal-only decisions.", decisions.get("signal", 0))
    lines += _gauge("bot_decisions_error", "Recent decision errors.", decisions.get("error", 0))
    lines += _gauge(
        "bot_dominant_block_reason",
        "Dominant recent block reason, encoded as a labeled gauge.",
        1,
        {"reason": dominant},
    )
    lines += _gauge("bot_paper_orderbook_trades", "Trades simulated against order book.", execution.get("paper_orderbook", 0))
    lines += _gauge("bot_live_trades", "Trades with live execution identifiers.", execution.get("live", 0))
    return "\n".join(lines) + "\n"
