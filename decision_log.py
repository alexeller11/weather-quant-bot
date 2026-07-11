#!/usr/bin/env python3
"""
Decision telemetry for the paper/live validation loop.

The bot can only be validated for real money if we can explain both sides:
why it entered a trade and why it skipped every other candidate.  This module
keeps that audit trail in a local JSONL file and exposes compact summaries for
the dashboard.
"""

import json
import os
import threading
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional


DECISION_LOG_FILE = os.environ.get("DECISION_LOG_FILE", "decision_log.jsonl")
_LOCK = threading.RLock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _simple(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    try:
        return float(value)
    except Exception:
        return str(value)[:500]


def _market_fields(market: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(market, dict):
        return {}
    keys = (
        "market_id",
        "market_key",
        "gamma_market_id",
        "gamma_event_id",
        "event_slug",
        "question",
        "market_date",
        "condition",
        "target",
        "target_lo",
        "target_hi",
        "unit",
        "yes_price",
        "no_price",
        "yes_token_id",
        "no_token_id",
        "liquidity",
        "volume",
        "spread",
    )
    return {k: _simple(market.get(k)) for k in keys if market.get(k) is not None}


def record_decision(
    status: str,
    reason: str,
    *,
    city: Optional[str] = None,
    market: Optional[Dict[str, Any]] = None,
    side: Optional[str] = None,
    **fields: Any,
) -> bool:
    """
    Append one decision event.

    status examples: blocked, error, recorded, signal.
    reason examples: no_markets, guardrail_failed, trade_recorded.
    """
    event: Dict[str, Any] = {
        "ts": _now_iso(),
        "status": str(status),
        "reason": str(reason),
    }
    if city:
        event["city"] = str(city)
    if side:
        event["side"] = str(side).upper()
    event.update(_market_fields(market))
    for key, value in fields.items():
        if value is not None:
            event[key] = _simple(value)

    try:
        with _LOCK:
            with open(DECISION_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        return True
    except Exception:
        return False


def load_decisions(limit: int = 500) -> List[Dict[str, Any]]:
    if limit <= 0:
        return []
    try:
        with _LOCK:
            with open(DECISION_LOG_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()[-limit:]
    except FileNotFoundError:
        return []
    except Exception:
        return []

    events = []
    for line in lines:
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                events.append(item)
        except Exception:
            continue
    return events


def summarize_decisions(events: Optional[Iterable[Dict[str, Any]]] = None, limit: int = 500) -> Dict[str, Any]:
    items = list(events) if events is not None else load_decisions(limit=limit)
    by_status = Counter(str(e.get("status", "?")) for e in items)
    by_reason = Counter(str(e.get("reason", "?")) for e in items)
    recent = list(reversed(items[-30:]))
    trade_events = [e for e in items if e.get("reason") in ("trade_recorded", "signal")]
    return {
        "total": len(items),
        "by_status": dict(by_status.most_common()),
        "by_reason": dict(by_reason.most_common(12)),
        "recent": recent,
        "last_ts": items[-1].get("ts") if items else None,
        "last_trade_ts": trade_events[-1].get("ts") if trade_events else None,
        "blocked_count": by_status.get("blocked", 0),
        "recorded_count": by_status.get("recorded", 0),
        "signal_count": by_status.get("signal", 0),
        "error_count": by_status.get("error", 0),
    }


def _avg(values: List[float]) -> Optional[float]:
    return round(sum(values) / len(values), 4) if values else None


def trade_execution_summary(history: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    trades = list(history or [])
    orderbook = [t for t in trades if bool(t.get("paper_execution"))]
    live = [
        t for t in trades
        if t.get("real_order_id") or t.get("clob_order_id") or t.get("order_hash")
    ]
    legacy = [t for t in trades if t not in orderbook and t not in live]

    slippages = [float(t.get("slippage")) for t in orderbook if t.get("slippage") is not None]
    fill_ratios = [float(t.get("fill_ratio")) for t in orderbook if t.get("fill_ratio") is not None]
    filled_costs = [float(t.get("filled_cost") or t.get("stake") or 0) for t in orderbook]
    stakes = [float(t.get("stake") or 0) for t in orderbook]
    closed_orderbook = [t for t in orderbook if t.get("result") in ("WIN", "LOSS")]
    tiny = [t for t in orderbook if float(t.get("stake") or 0) < 1.0]

    return {
        "paper_orderbook": len(orderbook),
        "legacy_paper": len(legacy),
        "live": len(live),
        "open_orderbook": sum(1 for t in orderbook if t.get("result") == "OPEN"),
        "closed_orderbook": len(closed_orderbook),
        "avg_slippage": _avg(slippages),
        "avg_fill_ratio": _avg(fill_ratios),
        "avg_requested_stake": _avg(stakes),
        "avg_filled_cost": _avg(filled_costs),
        "orderbook_total_stake": round(sum(stakes), 4),
        "legacy_total_stake": round(sum(float(t.get("stake") or 0) for t in legacy), 4),
        "tiny_orderbook_trades": len(tiny),
        "last_orderbook_trade": orderbook[-1].get("entry_time") if orderbook else None,
    }
