#!/usr/bin/env python3
"""
Weather Model - Probabilidade baseada em distribuição Normal,
com sigma calibrado por cidade e ajuste de ML online.

Cálculo correto por tipo de condição:
  ABOVE  → P(temp > target)   = 1 - CDF(z)
  BELOW  → P(temp < target)   = CDF(z)
  EXACT  → P(|temp - target| <= 0.5°C) = CDF(z_high) - CDF(z_low)
           Probabilidades EXACT são tipicamente 10-35%, nunca 90%+.
"""

import logging
from scipy import stats

from sigma_calibrator import SigmaCalibrator
from ml_adjuster import MLProbabilityAdjuster

logger = logging.getLogger(__name__)

_calibrator  = SigmaCalibrator()
_ml_adjuster = MLProbabilityAdjuster()

# Janela de tolerância para mercados EXACT (±0.5°C em cada lado)
EXACT_WINDOW_C = 0.5


def get_base_sigma(day_offset: int) -> float:
    """Retorna o sigma base para o horizonte de previsão."""
    return {1: 2.8, 2: 3.2, 3: 3.5}.get(day_offset, 3.5)


def calculate_probability(
    city: str,
    target_temp: float,
    forecast_temp: float,
    day_offset: int,
    condition: str = "ABOVE",
    unit: str = "C",
) -> float:
    """
    Retorna a probabilidade (0 a 1) de o mercado resolver YES.

    Parâmetros
    ----------
    city          : nome da cidade (usado para calibração de sigma)
    target_temp   : temperatura alvo do mercado (na unidade do mercado)
    forecast_temp : temperatura prevista em °C
    day_offset    : dias de antecedência (1, 2, 3)
    condition     : "ABOVE", "BELOW" ou "EXACT"
    unit          : "C" ou "F" — unidade do target_temp

    Conversão de unidade
    --------------------
    forecast_temp está sempre em °C (vem do Open-Meteo).
    Se unit == "F", converte target para °C antes de calcular.
    """
    # Normaliza condição
    cond = condition.upper().strip()

    # Converte target para °C se necessário
    if unit.upper() == "F":
        target_c = (target_temp - 32) * 5 / 9
    else:
        target_c = float(target_temp)

    forecast_c = float(forecast_temp)

    # Sigma calibrado
    base_sigma = get_base_sigma(day_offset)
    sigma = _calibrator.get_adjusted_sigma(city, base_sigma)
    sigma = max(sigma, 0.5)  # nunca deixa sigma ir a zero

    # ── Cálculo por tipo ──────────────────────────────────────────────

    if cond == "ABOVE":
        # P(temp > target) = 1 - Φ((target - forecast) / sigma)
        z = (target_c - forecast_c) / sigma
        model_prob = 1.0 - stats.norm.cdf(z)

    elif cond == "BELOW":
        # P(temp < target) = Φ((target - forecast) / sigma)
        z = (target_c - forecast_c) / sigma
        model_prob = stats.norm.cdf(z)

    elif cond == "EXACT":
        # P(|temp - target| <= 0.5°C)
        # = Φ((target + 0.5 - forecast) / sigma)
        # - Φ((target - 0.5 - forecast) / sigma)
        z_high = (target_c + EXACT_WINDOW_C - forecast_c) / sigma
        z_low  = (target_c - EXACT_WINDOW_C - forecast_c) / sigma
        model_prob = stats.norm.cdf(z_high) - stats.norm.cdf(z_low)

    else:
        # Fallback seguro para condições desconhecidas
        logger.warning(f"Condição desconhecida '{condition}' — usando 0.0")
        model_prob = 0.0

    # Ajuste ML (só tem efeito se houver dados suficientes)
    adjusted_prob = _ml_adjuster.adjust_probability(
        model_prob=model_prob,
        day_offset=day_offset,
        city=city,
        calibrator=_calibrator,
    )

    logger.debug(
        f"{city} D+{day_offset} [{cond}]: "
        f"target={target_temp}{unit} ({target_c:.1f}°C) "
        f"forecast={forecast_c:.1f}°C sigma={sigma:.2f} "
        f"prob_raw={model_prob:.3f} prob_adj={adjusted_prob:.3f}"
    )

    return float(adjusted_prob)


def get_calibrator():
    return _calibrator


def get_ml_adjuster():
    return _ml_adjuster
