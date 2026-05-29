#!/usr/bin/env python3
"""
Weather Model — Probabilidade baseada em distribuição Normal.

CORREÇÕES v4:
  1. calculate_probability() agora aceita 'condition' e usa fórmula correta
     por tipo de mercado:
       ABOVE → P(X > target)         = Φ((forecast - target) / sigma)
       BELOW → P(X < target)         = 1 - Φ((forecast - target) / sigma)
       EXACT → P(|X - target| ≤ 0.5) = Φ((forecast - target + 0.5) / sigma)
                                      - Φ((forecast - target - 0.5) / sigma)

  2. Bug anterior: EXACT usava a mesma fórmula de ABOVE, produzindo
     probabilidades > 0.90 quando forecast estava 5°C acima do target.
     Exemplo real: Toronto target=18, forecast=25.5, sigma=2.8
       Antes: P(25.5 > 18) = 0.9963  ← completamente errado
       Agora: P(|T-18| ≤ 0.5) = 0.0041  ← correto, não entrar nesse trade
"""

import logging
from scipy import stats

from sigma_calibrator import SigmaCalibrator
from ml_adjuster import MLProbabilityAdjuster

logger = logging.getLogger(__name__)

_calibrator  = SigmaCalibrator()
_ml_adjuster = MLProbabilityAdjuster()


def get_base_sigma(day_offset: int) -> float:
    """Sigma base calibrado pelo erro real observado nos 26 trades iniciais."""
    return {1: 2.8, 2: 3.2, 3: 3.5}.get(day_offset, 4.0)


def to_celsius(value: float, unit: str) -> float:
    """Converte valor para Celsius se necessário."""
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
) -> float:
    """
    Retorna a probabilidade do mercado resolver YES.

    Parâmetros:
        city          — nome da cidade (para ajuste ML)
        target_temp   — temperatura alvo na unidade original do mercado
        forecast_temp — previsão Open-Meteo em °C
        day_offset    — horizonte de previsão (1, 2, 3...)
        condition     — "ABOVE", "BELOW" ou "EXACT"
        unit          — "C" ou "F" (unidade do target_temp)

    Retorna float em [0, 1].
    """
    condition = condition.upper()

    # Converte target para Celsius para comparar com forecast (sempre em °C)
    target_c = to_celsius(target_temp, unit)

    base_sigma = get_base_sigma(day_offset)
    sigma = _calibrator.get_adjusted_sigma(city, base_sigma)

    # Evita divisão por zero
    if sigma <= 0:
        sigma = base_sigma

    # ── Fórmula por condição ──────────────────────────────────────────────
    if condition == "ABOVE":
        # P(X > target) com X ~ N(forecast, sigma)
        z = (forecast_temp - target_c) / sigma
        model_prob = stats.norm.cdf(z)

    elif condition == "BELOW":
        # P(X < target)
        z = (forecast_temp - target_c) / sigma
        model_prob = 1.0 - stats.norm.cdf(z)

    elif condition == "EXACT":
        # P(|X - target| ≤ 0.5)
        # = Φ((forecast - target + 0.5) / sigma) - Φ((forecast - target - 0.5) / sigma)
        z_high = (forecast_temp - (target_c - 0.5)) / sigma
        z_low  = (forecast_temp - (target_c + 0.5)) / sigma
        model_prob = stats.norm.cdf(z_high) - stats.norm.cdf(z_low)

    else:
        logger.warning(f"Condição desconhecida: {condition}, usando ABOVE")
        z = (forecast_temp - target_c) / sigma
        model_prob = stats.norm.cdf(z)

    model_prob = max(0.0, min(1.0, model_prob))

    # Ajuste ML (apenas quando há dados suficientes)
    adjusted_prob = _ml_adjuster.adjust_probability(
        model_prob=model_prob,
        day_offset=day_offset,
        city=city,
        calibrator=_calibrator,
    )
    adjusted_prob = max(0.0, min(1.0, adjusted_prob))

    logger.debug(
        f"{city} D+{day_offset} {condition} {target_temp}°{unit}: "
        f"forecast={forecast_temp:.1f}°C target_c={target_c:.1f}°C "
        f"sigma={sigma:.2f} prob_raw={model_prob:.4f} prob_adj={adjusted_prob:.4f}"
    )

    return adjusted_prob


def get_calibrator():
    return _calibrator


def get_ml_adjuster():
    return _ml_adjuster
