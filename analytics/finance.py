"""
analytics.finance

Métricas financeiras do Weather Quant.

Todas as funções são PURAS.
Nunca acessam arquivos.
Nunca acessam banco.
Nunca fazem logging.

Recebem TradeDataset e retornam valores.
"""

from __future__ import annotations

from statistics import mean, pstdev
import math

from .dataset import TradeDataset


# ============================================================
# Helpers
# ============================================================

def closed(dataset: TradeDataset):
    return dataset.closed_trades


def winning(dataset: TradeDataset):
    return dataset.wins


def losing(dataset: TradeDataset):
    return dataset.losses


# ============================================================
# Lucro
# ============================================================

def total_profit(dataset: TradeDataset) -> float:
    """
    Soma apenas pnl positivo.
    """
    return sum(
        max(0.0, float(t.get("pnl", 0.0)))
        for t in closed(dataset)
    )


def total_loss(dataset: TradeDataset) -> float:
    """
    Soma absoluta do pnl negativo.
    """
    return abs(
        sum(
            min(0.0, float(t.get("pnl", 0.0)))
            for t in closed(dataset)
        )
    )


def total_pnl(dataset: TradeDataset) -> float:
    return sum(
        float(t.get("pnl", 0.0))
        for t in closed(dataset)
    )


# ============================================================
# Stake
# ============================================================

def total_stake(dataset: TradeDataset) -> float:
    return sum(
        float(t.get("stake", 0.0))
        for t in closed(dataset)
    )


def average_stake(dataset: TradeDataset) -> float:

    trades = closed(dataset)

    if not trades:
        return 0.0

    return mean(
        float(t.get("stake", 0.0))
        for t in trades
    )


# ============================================================
# ROI
# ============================================================

def roi(dataset: TradeDataset) -> float:
    """
    ROI baseado em stake investido.
    """

    stake = total_stake(dataset)

    if stake <= 0:
        return 0.0

    return total_pnl(dataset) / stake


# ============================================================
# Win Rate
# ============================================================

def win_rate(dataset: TradeDataset) -> float:

    wins = len(dataset.wins)

    losses = len(dataset.losses)

    total = wins + losses

    if total == 0:
        return 0.0

    return wins / total


# ============================================================
# Expectancy
# ============================================================

def expectancy(dataset: TradeDataset) -> float:

    trades = dataset.wins + dataset.losses

    if not trades:
        return 0.0

    return mean(
        float(t.get("pnl", 0.0))
        for t in trades
    )


# ============================================================
# Profit Factor
# ============================================================

def profit_factor(dataset: TradeDataset) -> float:

    gp = total_profit(dataset)

    gl = total_loss(dataset)

    if gl == 0:

        return float("inf") if gp else 0.0

    return gp / gl


# ============================================================
# Equity Curve
# ============================================================

def equity_curve(dataset: TradeDataset):

    return dataset.equity_curve.copy()


# ============================================================
# Drawdown
# ============================================================

def current_drawdown(dataset: TradeDataset) -> float:

    curve = equity_curve(dataset)

    if len(curve) < 2:
        return 0.0

    peak = max(curve)

    current = curve[-1]

    if peak <= 0:
        return 0.0

    return (peak - current) / peak


def max_drawdown(dataset: TradeDataset) -> float:

    curve = equity_curve(dataset)

    if len(curve) < 2:
        return 0.0

    peak = curve[0]

    max_dd = 0.0

    for value in curve:

        if value > peak:
            peak = value

        if peak <= 0:
            continue

        dd = (peak - value) / peak

        max_dd = max(max_dd, dd)

    return max_dd


# ============================================================
# Recovery Factor
# ============================================================

def recovery_factor(dataset: TradeDataset):

    dd = max_drawdown(dataset)

    if dd <= 0:
        return 0.0

    return total_pnl(dataset) / dd


# ============================================================
# Returns
# ============================================================

def trade_returns(dataset: TradeDataset):

    values = []

    for trade in dataset.wins + dataset.losses:

        stake = float(trade.get("stake", 0))

        if stake <= 0:
            continue

        pnl = float(trade.get("pnl", 0))

        values.append(pnl / stake)

    return values


# ============================================================
# Sharpe
# ============================================================

def sharpe(dataset: TradeDataset, risk_free_rate=0.0):

    returns = trade_returns(dataset)

    if len(returns) < 2:
        return 0.0

    std = pstdev(returns)

    if std <= 1e-9:
        return 0.0

    return (mean(returns) - risk_free_rate) / std


# ============================================================
# Sortino
# ============================================================

def sortino(dataset: TradeDataset, risk_free_rate=0.0):

    returns = trade_returns(dataset)

    if len(returns) < 2:
        return 0.0

    downside = [

        r

        for r in returns

        if r < risk_free_rate

    ]

    if len(downside) < 2:
        return 0.0

    downside_std = math.sqrt(

        sum(

            (r-risk_free_rate)**2

            for r in downside

        ) / len(downside)

    )

    if downside_std <= 1e-9:
        return 0.0

    return (mean(returns)-risk_free_rate)/downside_std


# ============================================================
# Calmar
# ============================================================

def calmar(dataset: TradeDataset):

    dd = max_drawdown(dataset)

    if dd <= 0:
        return 0.0

    return roi(dataset) / dd


# ============================================================
# Summary
# ============================================================

def summary(dataset: TradeDataset) -> dict:
    """
    Resumo financeiro usado pelo Analytics Engine.
    """

    return {

        "balance": dataset.balance,

        "start_balance": dataset.start_balance,

        "profit": total_profit(dataset),

        "loss": total_loss(dataset),

        "pnl": total_pnl(dataset),

        "stake": total_stake(dataset),

        "roi": roi(dataset),

        "win_rate": win_rate(dataset),

        "expectancy": expectancy(dataset),

        "profit_factor": profit_factor(dataset),

        "drawdown": current_drawdown(dataset),

        "max_drawdown": max_drawdown(dataset),

        "recovery_factor": recovery_factor(dataset),

        "sharpe": sharpe(dataset),

        "sortino": sortino(dataset),

        "calmar": calmar(dataset),

    }
