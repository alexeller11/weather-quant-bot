#!/usr/bin/env python3
"""
model.py — Probabilidade baseada em distribuição Normal

CORRIGIDO: suporte ao novo tipo "range2" (bucket de 2°F/°C da Polymarket).

Para range2: P(target_lo <= X <= target_hi)
  = Φ((forecast - target_lo) / sigma) - Φ((forecast - target_hi) / sigma)

Exemplo real: forecast=74.1°F, sigma=4°F, bucket="74-75°F"
  P(74 <= X <= 75) = Φ(0.025) - Φ(-0.225) ≈ 0.51 - 0.41 = 10%
  Se o mercado paga 0.06, edge = +4pp — trade válido.
"""

import logging
from scipy import stats

from sigma_calibrator import SigmaCalibrator
from ml_adjuster import MLProbabilityAdjuster

logger = logging.getLogger(__name__)

_calibrator  = SigmaCalibrator()
_ml_adjuster = MLProbabilityAdjuster()


def get_base_sigma(day_offset: int) -> float:
    """Sigma base recalibrado após 39 trades reais."""
    return {1: 4.0, 2: 4.5, 3: 5.0}.get(day_offset, 6.0)


def to_celsius(value: float, unit: str) -> float:
    if str(unit).upper() == "F":
        return (value - 32) * 5 / 9
    return value


def calculate_probability(
    city: str,
    target_temp: float,
    forecast_temp: float,
    day_offset: int,
    condition: str = "ABOVE",
    unit: str = "C",
    sigma: float = None,
    target_lo: float = None,
    target_hi: float = None,
) -> float:
    """
    Retorna probabilidade do mercado resolver YES.

    Parâmetros extras para range2:
        target_lo — limite inferior do bucket (na unidade original)
        target_hi — limite superior do bucket (na unidade original)
    """
    condition = condition.upper()

    target_c = to_celsius(target_temp, unit)

    if sigma is None or sigma <= 0:
        base_sigma = get_base_sigma(day_offset)
        sigma = _calibrator.get_adjusted_sigma(city, base_sigma)
        if sigma <= 0:
            sigma = base_sigma

    if condition == "ABOVE":
        z = (forecast_temp - target_c) / sigma
        model_prob = stats.norm.cdf(z)

    elif condition == "BELOW":
        z = (forecast_temp - target_c) / sigma
        model_prob = 1.0 - stats.norm.cdf(z)

    elif condition == "EXACT":
        z_high = (forecast_temp - (target_c - 0.5)) / sigma
        z_low  = (forecast_temp - (target_c + 0.5)) / sigma
        model_prob = stats.norm.cdf(z_high) - stats.norm.cdf(z_low)

    elif condition == "RANGE2":
        # NOVO: bucket de 2°F ou 2°C
        # Converte limites para Celsius
        lo_c = to_celsius(target_lo, unit) if target_lo is not None else target_c - 1
        hi_c = to_celsius(target_hi, unit) if target_hi is not None else target_c + 1
        # P(lo <= X <= hi) com X ~ N(forecast, sigma)
        z_hi = (forecast_temp - lo_c) / sigma
        z_lo = (forecast_temp - hi_c) / sigma
        model_prob = stats.norm.cdf(z_hi) - stats.norm.cdf(z_lo)

    else:
        return 0.0

    model_prob = max(0.0, min(1.0, model_prob))

    # Ajuste ML apenas quando há dados suficientes
    adjusted_prob = _ml_adjuster.adjust_probability(
        model_prob=model_prob,
        day_offset=day_offset,
        city=city,
        calibrator=_calibrator,
    )
    adjusted_prob = max(0.0, min(1.0, adjusted_prob))

    logger.debug(
        f"{city} D+{day_offset} {condition} {target_temp}°{unit}: "
        f"forecast={forecast_temp:.1f}°C sigma={sigma:.2f} "
        f"prob_raw={model_prob:.4f} prob_adj={adjusted_prob:.4f}"
    )

    return adjusted_prob


def get_calibrator():
    return _calibrator


def get_ml_adjuster():
    return _ml_adjuster
