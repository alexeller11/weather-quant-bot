
"""
analytics/performance.py (v2)

Rankings e análise de desempenho.
"""

from __future__ import annotations

from .dataset import TradeDataset, build_dataset_from_history
from .finance import summary as finance_summary
from .statistics import summary as statistics_summary


def _summary(dataset: TradeDataset):

    result = {}

    result.update(finance_summary(dataset))
    result.update(statistics_summary(dataset))

    result["trades"] = dataset.trades
    result["wins"] = len(dataset.wins)
    result["losses"] = len(dataset.losses)
    result["voids"] = len(dataset.voids)
    result["open"] = len(dataset.open_trades)

    return result


def _rank(groups):

    ranking = {}

    for key, trades in groups.items():

        ds = build_dataset_from_history(trades)

        ranking[key] = _summary(ds)

    return dict(
        sorted(
            ranking.items(),
            key=lambda item: item[1].get("roi", 0.0),
            reverse=True,
        )
    )


def by_city(dataset: TradeDataset):
    return _rank(dataset.by_city)


def by_market(dataset: TradeDataset):
    return _rank(dataset.by_market)


def by_forecast_day(dataset: TradeDataset):
    return _rank(dataset.by_day)


def by_month(dataset: TradeDataset):
    return _rank(dataset.by_month)


def by_season(dataset: TradeDataset):
    return _rank(dataset.by_season)


def best(dictionary):

    if not dictionary:
        return None

    key = next(iter(dictionary))
    return key, dictionary[key]


def worst(dictionary):

    if not dictionary:
        return None

    key = list(dictionary.keys())[-1]
    return key, dictionary[key]


def summary(dataset: TradeDataset):

    cities = by_city(dataset)
    markets = by_market(dataset)
    forecast = by_forecast_day(dataset)
    months = by_month(dataset)
    seasons = by_season(dataset)

    return {

        "cities": cities,

        "markets": markets,

        "forecast_days": forecast,

        "months": months,

        "seasons": seasons,

        "best_city": best(cities),
        "worst_city": worst(cities),

        "best_market": best(markets),
        "worst_market": worst(markets),

        "best_forecast_day": best(forecast),
        "worst_forecast_day": worst(forecast),
    }
