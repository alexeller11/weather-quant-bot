
"""
analytics/health.py (v2)

Health Engine do Weather Quant.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, List

MIN_TRADES = 30
MAX_ECE = 0.15
MAX_DRAWDOWN = 0.20
MIN_SHARPE = 0.80
MIN_ROI = 0.00
MIN_CALIBRATION = 0.85


@dataclass
class HealthReport:
    score: float
    status: str
    kelly_factor: float
    paper_mode: bool
    stop_trading: bool
    recommendation: str
    alerts: List[str]


def _status(score: float) -> str:
    if score >= 90: return "GREEN"
    if score >= 75: return "YELLOW"
    if score >= 60: return "ORANGE"
    if score >= 40: return "RED"
    return "BLACK"


def _kelly(score: float) -> float:
    if score >= 90: return 1.0
    if score >= 80: return 0.8
    if score >= 70: return 0.6
    if score >= 60: return 0.4
    if score >= 50: return 0.2
    return 0.0


def evaluate(metrics: Dict) -> HealthReport:
    alerts = []
    penalties = 0

    trades = metrics.get("trades", 0)
    roi = metrics.get("roi", 0.0)
    sharpe = metrics.get("sharpe", 0.0)
    drawdown = metrics.get("max_drawdown", 0.0)
    ece = metrics.get("ece", 0.0)
    calibration = metrics.get("calibration_quality", 1.0)
    pf = metrics.get("profit_factor", 0.0)

    if trades < MIN_TRADES:
        penalties += 10
        alerts.append(f"Poucos trades ({trades})")

    if roi < MIN_ROI:
        penalties += 20
        alerts.append(f"ROI negativo ({roi:.2%})")

    if sharpe < MIN_SHARPE:
        penalties += 15
        alerts.append(f"Sharpe baixo ({sharpe:.2f})")

    if drawdown > MAX_DRAWDOWN:
        penalties += 20
        alerts.append(f"Drawdown alto ({drawdown:.2%})")

    if ece > MAX_ECE:
        penalties += 20
        alerts.append(f"ECE alto ({ece:.3f})")

    if calibration < MIN_CALIBRATION:
        penalties += 10
        alerts.append(f"Calibração ruim ({calibration:.2%})")

    if pf < 1:
        penalties += 10
        alerts.append(f"Profit Factor baixo ({pf:.2f})")

    score = max(0.0, 100.0 - penalties)

    paper = score < 60
    stop = score < 40

    if stop:
        rec = "Parar operações."
    elif paper:
        rec = "Entrar em Paper Trading."
    elif score < 80:
        rec = "Reduzir Kelly e monitorar."
    else:
        rec = "Operação normal."

    return HealthReport(
        score=round(score,2),
        status=_status(score),
        kelly_factor=_kelly(score),
        paper_mode=paper,
        stop_trading=stop,
        recommendation=rec,
        alerts=alerts,
    )


def to_dict(report: HealthReport):
    return asdict(report)
