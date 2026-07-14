"""
analytics.dataset

TradeDataset é a representação canônica do estado do Weather Quant
para análises.

Todos os módulos de Analytics trabalham SOMENTE com este objeto.

Nunca ler bankroll.json diretamente dentro de finance.py,
statistics.py, performance.py ou health.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional


Trade = Dict


@dataclass
class TradeDataset:
    """
    Snapshot do bankroll convertido para um formato próprio para
    cálculos estatísticos.
    """

    # bankroll
    balance: float
    start_balance: float
    seq: int

    created_at: Optional[str]

    generated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    # trades
    history: List[Trade] = field(default_factory=list)

    open_trades: List[Trade] = field(default_factory=list)

    closed_trades: List[Trade] = field(default_factory=list)

    wins: List[Trade] = field(default_factory=list)

    losses: List[Trade] = field(default_factory=list)

    voids: List[Trade] = field(default_factory=list)

    # equity
    equity_curve: List[float] = field(default_factory=list)

    # índices
    by_city: Dict[str, List[Trade]] = field(default_factory=dict)

    by_market: Dict[str, List[Trade]] = field(default_factory=dict)

    by_day: Dict[int, List[Trade]] = field(default_factory=dict)

    by_month: Dict[int, List[Trade]] = field(default_factory=dict)

    by_season: Dict[str, List[Trade]] = field(default_factory=dict)

    @property
    def trades(self) -> int:
        return len(self.history)


def build_dataset(bankroll: Dict) -> TradeDataset:
    """
    Converte bankroll -> TradeDataset.

    Esta função é chamada apenas pelo Analytics Engine.
    """

    history = bankroll.get("history", [])

    dataset = TradeDataset(
        balance=float(bankroll.get("balance", 0.0)),
        start_balance=float(bankroll.get("start_balance", 0.0)),
        seq=int(bankroll.get("seq", 0)),
        created_at=bankroll.get("created_at"),
        history=history,
    )

    #
    # separação dos trades
    #

    for trade in history:

        result = str(trade.get("result", "")).upper()

        if result == "OPEN":
            dataset.open_trades.append(trade)

        else:
            dataset.closed_trades.append(trade)

        if result == "WIN":
            dataset.wins.append(trade)

        elif result == "LOSS":
            dataset.losses.append(trade)

        elif result == "VOID":
            dataset.voids.append(trade)

        #
        # cidade
        #

        city = (
            trade.get("city")
            or trade.get("city_slug")
            or "unknown"
        )

        dataset.by_city.setdefault(city, []).append(trade)

        #
        # tipo
        #

        market = (
            trade.get("condition")
            or trade.get("type")
            or "UNKNOWN"
        )

        dataset.by_market.setdefault(market, []).append(trade)

        #
        # horizonte
        #

        forecast_day = int(
            trade.get("forecast_day", 0) or 0
        )

        dataset.by_day.setdefault(
            forecast_day,
            []
        ).append(trade)

        #
        # mês
        #

        market_date = trade.get("market_date")

        if market_date:

            try:

                month = int(str(market_date)[5:7])

                dataset.by_month.setdefault(
                    month,
                    []
                ).append(trade)

                #
                # estação
                #

                if month in (12, 1, 2):
                    season = "SUMMER"

                elif month in (3, 4, 5):
                    season = "AUTUMN"

                elif month in (6, 7, 8):
                    season = "WINTER"

                else:
                    season = "SPRING"

                dataset.by_season.setdefault(
                    season,
                    []
                ).append(trade)

            except Exception:
                pass

    #
    # curva de patrimônio
    #

    balance = dataset.start_balance

    dataset.equity_curve.append(balance)

    closed = sorted(
        dataset.closed_trades,
        key=lambda t: t.get("exit_time", "")
    )

    for trade in closed:

        balance += float(trade.get("pnl", 0))

        dataset.equity_curve.append(balance)

    return dataset
