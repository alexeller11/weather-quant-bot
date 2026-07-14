"""
analytics.health

Health Engine do Weather Quant.

Transforma métricas em decisões operacionais.

Este módulo NÃO calcula métricas.
Ele apenas interpreta os resultados.

Pode ser usado para:

- Sistema inteiro
- Cidade
- Mercado
- Horizonte
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from .score import build as build_score


# ============================================================
# Configuração
# ============================================================

MIN_SAMPLE_SIZE = 30

MAX_BRIER = 0.25

MAX_DRAWDOWN = 0.25

MIN_SHARPE = 0.50

MIN_ROI = -0.05


# ============================================================
# Modelo
# ============================================================

@dataclass
class HealthReport:

    score: float

    status: str

    kelly_factor: float

    recommendation: str

    paper_mode: bool

    stop_trading: bool

    alerts: List[str]


# ============================================================
# Regras
# ============================================================

def evaluate(metrics: Dict) -> HealthReport:

    score = build_score(metrics)

    alerts = []

    paper = False

    stop = False

    trades = metrics.get("trades", 0)

    roi = metrics.get("roi", 0)

    brier = metrics.get("brier", 0)

    drawdown = metrics.get("max_drawdown", 0)

    sharpe = metrics.get("sharpe", 0)

    #
    # Pouca amostra
    #

    if trades < MIN_SAMPLE_SIZE:

        alerts.append(

            f"Apenas {trades} trades."

        )

    #
    # Brier
    #

    if brier > MAX_BRIER:

        alerts.append(

            f"Brier alto ({brier:.3f})"

        )

        paper = True

    #
    # Drawdown
    #

    if drawdown > MAX_DRAWDOWN:

        alerts.append(

            f"Drawdown alto ({drawdown:.1%})"

        )

    #
    # Sharpe
    #

    if sharpe < MIN_SHARPE:

        alerts.append(

            f"Sharpe baixo ({sharpe:.2f})"

        )

    #
    # ROI
    #

    if roi < MIN_ROI:

        alerts.append(

            f"ROI negativo ({roi:.1%})"

        )

    #
    # Black
    #

    if score["score"] < 40:

        stop = True

    return HealthReport(

        score=score["score"],

        status=score["status"],

        kelly_factor=score["kelly_factor"],

        recommendation=score["recommendation"],

        paper_mode=paper,

        stop_trading=stop,

        alerts=alerts,

    )


# ============================================================
# Cidade
# ============================================================

def city_health(city_metrics):

    return evaluate(city_metrics)


# ============================================================
# Mercado
# ============================================================

def market_health(metrics):

    return evaluate(metrics)


# ============================================================
# Horizonte
# ============================================================

def forecast_health(metrics):

    return evaluate(metrics)


# ============================================================
# Sistema
# ============================================================

def system_health(metrics):

    return evaluate(metrics)


# ============================================================
# JSON
# ============================================================

def to_dict(report: HealthReport):

    return {

        "score": report.score,

        "status": report.status,

        "kelly_factor": report.kelly_factor,

        "recommendation": report.recommendation,

        "paper_mode": report.paper_mode,

        "stop_trading": report.stop_trading,

        "alerts": report.alerts,

    }
