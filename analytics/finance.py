
"""
analytics/finance.py (v2)

Motor financeiro do Quant Intelligence Engine.
"""

from __future__ import annotations

import math
from statistics import mean, pstdev

from .dataset import TradeDataset


def _closed(ds: TradeDataset):
    return ds.closed_trades


def total_profit(ds):
    return sum(max(0.0, float(t.get("pnl", 0))) for t in _closed(ds))


def total_loss(ds):
    return abs(sum(min(0.0, float(t.get("pnl", 0))) for t in _closed(ds)))


def total_pnl(ds):
    return sum(float(t.get("pnl", 0)) for t in _closed(ds))


def total_stake(ds):
    return sum(float(t.get("stake", 0)) for t in _closed(ds))


def roi(ds):
    stake = total_stake(ds)
    return 0.0 if stake <= 0 else total_pnl(ds) / stake


def win_rate(ds):
    total = len(ds.wins) + len(ds.losses)
    return 0.0 if total == 0 else len(ds.wins) / total


def expectancy(ds):
    trades = ds.wins + ds.losses
    if not trades:
        return 0.0
    return mean(float(t.get("pnl", 0)) for t in trades)


def average_stake(ds):
    trades = _closed(ds)
    if not trades:
        return 0.0
    return mean(float(t.get("stake", 0)) for t in trades)


def profit_factor(ds):
    loss = total_loss(ds)
    if loss == 0:
        return float("inf") if total_profit(ds) else 0.0
    return total_profit(ds) / loss


def equity_curve(ds):
    return list(ds.equity_curve)


def max_drawdown(ds):
    curve = equity_curve(ds)
    if len(curve) < 2:
        return 0.0
    peak = curve[0]
    max_dd = 0.0
    for value in curve:
        peak = max(peak, value)
        if peak > 0:
            max_dd = max(max_dd, (peak - value) / peak)
    return max_dd


def current_drawdown(ds):
    curve = equity_curve(ds)
    if len(curve) < 2:
        return 0.0
    peak = max(curve)
    if peak <= 0:
        return 0.0
    return (peak - curve[-1]) / peak


def trade_returns(ds):
    values = []
    for t in ds.wins + ds.losses:
        stake = float(t.get("stake", 0))
        if stake > 0:
            values.append(float(t.get("pnl", 0)) / stake)
    return values


def sharpe(ds, risk_free_rate=0.0):
    r = trade_returns(ds)
    if len(r) < 2:
        return 0.0
    sd = pstdev(r)
    if sd <= 1e-9:
        return 0.0
    return (mean(r) - risk_free_rate) / sd


def sortino(ds, risk_free_rate=0.0):
    r = trade_returns(ds)
    if len(r) < 2:
        return 0.0
    downside = [x for x in r if x < risk_free_rate]
    if len(downside) < 2:
        return 0.0
    dd = math.sqrt(sum((x-risk_free_rate)**2 for x in downside)/len(downside))
    if dd <= 1e-9:
        return 0.0
    return (mean(r)-risk_free_rate)/dd


def calmar(ds):
    dd = max_drawdown(ds)
    return 0.0 if dd <= 0 else roi(ds)/dd


def recovery_factor(ds):
    dd = max_drawdown(ds)
    return 0.0 if dd <= 0 else total_pnl(ds)/dd


def summary(ds: TradeDataset):
    return {
        "balance": ds.balance,
        "start_balance": ds.start_balance,
        "trades": ds.trades,
        "profit": total_profit(ds),
        "loss": total_loss(ds),
        "pnl": total_pnl(ds),
        "stake": total_stake(ds),
        "average_stake": average_stake(ds),
        "roi": roi(ds),
        "win_rate": win_rate(ds),
        "expectancy": expectancy(ds),
        "profit_factor": profit_factor(ds),
        "drawdown": current_drawdown(ds),
        "max_drawdown": max_drawdown(ds),
        "recovery_factor": recovery_factor(ds),
        "sharpe": sharpe(ds),
        "sortino": sortino(ds),
        "calmar": calmar(ds),
    }
