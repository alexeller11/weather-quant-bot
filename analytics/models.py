"""
analytics.models

Modelos de dados do Analytics Engine.

Toda a comunicação entre os módulos deve utilizar estas dataclasses.
Nunca utilizar dicionários "soltos" dentro do Analytics.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict


# ===========================
# MÉTRICAS BÁSICAS
# ===========================

@dataclass
class BasicMetrics:

    trades: int = 0

    wins: int = 0

    losses: int = 0

    voids: int = 0

    open_trades: int = 0

    win_rate: float = 0.0

    roi: float = 0.0

    profit: float = 0.0

    loss: float = 0.0

    pnl: float = 0.0

    expectancy: float = 0.0

    average_stake: float = 0.0

    average_odds: float = 0.0

    average_ev: float = 0.0

    profit_factor: float = 0.0

    drawdown: float = 0.0

    max_drawdown: float = 0.0

    sharpe: float = 0.0

    sortino: float = 0.0

    calmar: float = 0.0

    brier: float = 0.0

    logloss: float = 0.0


# ===========================
# CIDADE
# ===========================

@dataclass
class CityMetrics(BasicMetrics):

    city: str = ""

    health: float = 100.0

    disabled: bool = False


# ===========================
# MERCADO
# ===========================

@dataclass
class MarketMetrics(BasicMetrics):

    market_type: str = ""

    health: float = 100.0

    disabled: bool = False


# ===========================
# HORIZONTE
# ===========================

@dataclass
class ForecastMetrics(BasicMetrics):

    forecast_day: int = 0

    health: float = 100.0

    disabled: bool = False


# ===========================
# HEALTH
# ===========================

@dataclass
class HealthMetrics:

    score: float = 100.0

    status: str = "GREEN"

    paper_mode: bool = False

    stop_trading: bool = False

    kelly_factor: float = 1.0

    disabled_cities: list = field(default_factory=list)

    disabled_markets: list = field(default_factory=list)

    disabled_days: list = field(default_factory=list)


# ===========================
# SNAPSHOT
# ===========================

@dataclass
class AnalyticsSnapshot:

    generated_at: datetime

    overall: BasicMetrics

    cities: Dict[str, CityMetrics] = field(default_factory=dict)

    markets: Dict[str, MarketMetrics] = field(default_factory=dict)

    forecast_days: Dict[int, ForecastMetrics] = field(default_factory=dict)

    health: HealthMetrics = field(default_factory=HealthMetrics)
