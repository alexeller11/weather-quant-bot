"""
analytics.performance

Análise de performance por segmentos.

Nunca acessa arquivos.
Nunca faz logging.

Recebe TradeDataset e produz rankings.
"""

from __future__ import annotations

from typing import Dict

from .dataset import TradeDataset
from . import finance
from . import statistics


# ============================================================
# Helpers
# ============================================================

def _clone(dataset: TradeDataset, trades):

    clone = TradeDataset(
        balance=dataset.balance,
        start_balance=dataset.start_balance,
        seq=dataset.seq,
        created_at=dataset.created_at,
        history=list(trades),
    )

    for trade in clone.history:

        result = str(trade.get("result", "")).upper()

        if result == "OPEN":
            clone.open_trades.append(trade)

        else:
            clone.closed_trades.append(trade)

        if result == "WIN":
            clone.wins.append(trade)

        elif result == "LOSS":
            clone.losses.append(trade)

        elif result == "VOID":
            clone.voids.append(trade)

    balance = clone.start_balance

    clone.equity_curve.append(balance)

    for trade in sorted(
        clone.closed_trades,
        key=lambda t: t.get("exit_time", "")
    ):

        balance += float(trade.get("pnl", 0))

        clone.equity_curve.append(balance)

    return clone


def _summary(dataset):

    return {

        **finance.summary(dataset),

        **statistics.summary(dataset),

        "trades": len(dataset.history),

        "wins": len(dataset.wins),

        "losses": len(dataset.losses),

        "voids": len(dataset.voids),

        "open": len(dataset.open_trades),

    }


# ============================================================
# Cidade
# ============================================================

def by_city(dataset: TradeDataset):

    result = {}

    for city, trades in dataset.by_city.items():

        result[city] = _summary(

            _clone(dataset, trades)

        )

    return dict(

        sorted(

            result.items(),

            key=lambda x: x[1]["roi"],

            reverse=True

        )

    )


# ============================================================
# Mercado
# ============================================================

def by_market(dataset):

    result = {}

    for market, trades in dataset.by_market.items():

        result[market] = _summary(

            _clone(dataset, trades)

        )

    return dict(

        sorted(

            result.items(),

            key=lambda x: x[1]["roi"],

            reverse=True

        )

    )


# ============================================================
# Horizonte
# ============================================================

def by_forecast_day(dataset):

    result = {}

    for day, trades in dataset.by_day.items():

        result[day] = _summary(

            _clone(dataset, trades)

        )

    return dict(

        sorted(

            result.items(),

            key=lambda x: x[1]["roi"],

            reverse=True

        )

    )


# ============================================================
# Mês
# ============================================================

def by_month(dataset):

    result = {}

    for month, trades in dataset.by_month.items():

        result[month] = _summary(

            _clone(dataset, trades)

        )

    return dict(

        sorted(

            result.items(),

            key=lambda x: x[1]["roi"],

            reverse=True

        )

    )


# ============================================================
# Estação
# ============================================================

def by_season(dataset):

    result = {}

    for season, trades in dataset.by_season.items():

        result[season] = _summary(

            _clone(dataset, trades)

        )

    return dict(

        sorted(

            result.items(),

            key=lambda x: x[1]["roi"],

            reverse=True

        )

    )


# ============================================================
# Best / Worst
# ============================================================

def best_city(dataset):

    cities = by_city(dataset)

    if not cities:

        return None

    return next(iter(cities.items()))


def worst_city(dataset):

    cities = by_city(dataset)

    if not cities:

        return None

    return list(cities.items())[-1]


def best_market(dataset):

    markets = by_market(dataset)

    if not markets:

        return None

    return next(iter(markets.items()))


def worst_market(dataset):

    markets = by_market(dataset)

    if not markets:

        return None

    return list(markets.items())[-1]


def best_forecast_day(dataset):

    values = by_forecast_day(dataset)

    if not values:

        return None

    return next(iter(values.items()))


def worst_forecast_day(dataset):

    values = by_forecast_day(dataset)

    if not values:

        return None

    return list(values.items())[-1]


# ============================================================
# Dashboard
# ============================================================

def summary(dataset):

    return {

        "cities": by_city(dataset),

        "markets": by_market(dataset),

        "forecast_days": by_forecast_day(dataset),

        "months": by_month(dataset),

        "seasons": by_season(dataset),

        "best_city": best_city(dataset),

        "worst_city": worst_city(dataset),

        "best_market": best_market(dataset),

        "worst_market": worst_market(dataset),

        "best_day": best_forecast_day(dataset),

        "worst_day": worst_forecast_day(dataset),

    }
