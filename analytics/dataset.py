
"""
analytics/dataset.py (v2)

Camada de normalização entre o bankroll e o Analytics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections import defaultdict
from typing import Any, Dict, List


Trade = Dict[str, Any]


@dataclass
class TradeDataset:
    balance: float
    start_balance: float
    seq: int = 0
    created_at: str | None = None
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    history: List[Trade] = field(default_factory=list)

    closed_trades: List[Trade] = field(default_factory=list)
    open_trades: List[Trade] = field(default_factory=list)

    wins: List[Trade] = field(default_factory=list)
    losses: List[Trade] = field(default_factory=list)
    voids: List[Trade] = field(default_factory=list)

    equity_curve: List[float] = field(default_factory=list)

    by_city: Dict[str, List[Trade]] = field(default_factory=lambda: defaultdict(list))
    by_market: Dict[str, List[Trade]] = field(default_factory=lambda: defaultdict(list))
    by_day: Dict[int, List[Trade]] = field(default_factory=lambda: defaultdict(list))
    by_month: Dict[int, List[Trade]] = field(default_factory=lambda: defaultdict(list))
    by_season: Dict[str, List[Trade]] = field(default_factory=lambda: defaultdict(list))

    @property
    def trades(self) -> int:
        return len(self.history)


def _season(month: int) -> str:
    if month in (12, 1, 2):
        return "SUMMER"
    if month in (3, 4, 5):
        return "AUTUMN"
    if month in (6, 7, 8):
        return "WINTER"
    return "SPRING"


def build_dataset(bankroll: Dict[str, Any]) -> TradeDataset:
    ds = TradeDataset(
        balance=float(bankroll.get("balance", 0)),
        start_balance=float(bankroll.get("start_balance", 0)),
        seq=int(bankroll.get("seq", 0)),
        created_at=bankroll.get("created_at"),
    )

    ds.history = list(bankroll.get("history", []))

    balance = ds.start_balance
    ds.equity_curve.append(balance)

    closed_sorted = []

    for trade in ds.history:
        result = str(trade.get("result", "")).upper()

        if result == "OPEN":
            ds.open_trades.append(trade)
        else:
            ds.closed_trades.append(trade)
            closed_sorted.append(trade)

        if result == "WIN":
            ds.wins.append(trade)
        elif result == "LOSS":
            ds.losses.append(trade)
        elif result == "VOID":
            ds.voids.append(trade)

        city = (trade.get("city") or trade.get("city_slug") or "unknown").lower()
        ds.by_city[city].append(trade)

        market = (trade.get("type") or trade.get("condition") or "UNKNOWN").upper()
        ds.by_market[market].append(trade)

        day = int(trade.get("forecast_day", 0) or 0)
        ds.by_day[day].append(trade)

        market_date = trade.get("market_date")
        if isinstance(market_date, str) and len(market_date) >= 7:
            try:
                month = int(market_date[5:7])
                ds.by_month[month].append(trade)
                ds.by_season[_season(month)].append(trade)
            except Exception:
                pass

    closed_sorted.sort(key=lambda t: t.get("exit_time", ""))

    for trade in closed_sorted:
        balance += float(trade.get("pnl", 0))
        ds.equity_curve.append(round(balance, 4))

    return ds


def build_dataset_from_history(history, start_balance=0.0):
    bankroll = {
        "balance": start_balance,
        "start_balance": start_balance,
        "history": history,
    }
    return build_dataset(bankroll)
