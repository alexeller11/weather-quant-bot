#!/usr/bin/env python3
"""
Operational health for the long-running bot process.

`/healthz` only proves that the HTTP listener is alive.  This module answers
the more useful question: did the trading loop recently evaluate markets, is
the primary data store healthy, and why are entries not being recorded?
"""

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

from decision_log import load_decisions, summarize_decisions, trade_execution_summary


STALE_DECISION_SECONDS = 2 * 60 * 60


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
        summary = "loop ativo, mas PostgreSQL indisponivel"
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
