#!/usr/bin/env python3
"""
model.py — Probabilidade baseada em distribuição Normal

CORRIGIDO: suporte ao novo tipo "range2" (bucket de 2°F/°C da Polymarket).

Para range2: P(target_lo <= X <= target_hi)
  = Φ((forecast - target_lo) / sigma) - Φ((forecast - target_hi) / sigma)

Exemplo real: forecast=74.1°F, sigma=4°F, bucket="74-75°F"
  P(74 <= X <= 75) = Φ(0.025) - Φ(-0.225) ≈ 0.51 - 0.41 = 10%
  Se o mercado paga 0.06, edge = +4pp — trade válido.

CORREÇÕES (auditoria):
1. EXACT: a meia-largura do bucket agora é 0.5 na UNIDADE DO MERCADO,
   convertida para °C antes de entrar na Normal. Antes era 0.5°C fixo —
   para mercados em °F isso superestimava a largura do bucket em 80%
   (0.5°F ≈ 0.278°C) e, portanto, a probabilidade do EXACT.
2. RANGE2 sem limites explícitos: o fallback ±1 agora também é na
   unidade do mercado convertida (antes era ±1°C fixo).
3. O sigma calibrado por cidade agora recebe a CONDIÇÃO do mercado
   (ABOVE/BELOW/EXACT/RANGE2). O calibrador guarda ajustes separados por
   condição, mas era consultado sempre com o default "ABOVE".
4. O ajuste ML recebe a hora UTC atual (a mesma semântica usada no
   treino via settlement), eliminando o train/serve skew do hour=12 fixo.
"""

import logging
from datetime import datetime, timezone

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
    """Converte um VALOR ABSOLUTO de temperatura para °C."""
    if str(unit).upper() == "F":
        return (value - 32) * 5 / 9
    return value


def delta_to_celsius(delta: float, unit: str) -> float:
    """
    Converte uma DIFERENÇA/LARGURA de temperatura para °C.
    Diferente de to_celsius: largura de 0.5°F = 0.5 × 5/9 ≈ 0.2778°C
    (sem o offset de -32, que só se aplica a valores absolutos).
    """
    if str(unit).upper() == "F":
        return delta * 5 / 9
    return delta


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
        sigma = _calibrator.get_adjusted_sigma(city, base_sigma, condition=condition)
        if sigma <= 0:
            sigma = base_sigma

    if condition == "ABOVE":
        z = (forecast_temp - target_c) / sigma
        model_prob = stats.norm.cdf(z)

    elif condition == "BELOW":
        z = (forecast_temp - target_c) / sigma
        model_prob = 1.0 - stats.norm.cdf(z)

    elif condition == "EXACT":
        # Bucket de ±0.5 na UNIDADE DO MERCADO, convertido para °C.
        # Em °F: 0.5°F ≈ 0.2778°C; em °C: 0.5°C.
        half = delta_to_celsius(0.5, unit)
        z_high = (forecast_temp - (target_c - half)) / sigma
        z_low  = (forecast_temp - (target_c + half)) / sigma
        model_prob = stats.norm.cdf(z_high) - stats.norm.cdf(z_low)

    elif condition == "RANGE2":
        # Bucket de 2°F ou 2°C — converte limites para Celsius.
        # Fallback (sem limites explícitos): ±1 na unidade do mercado.
        fallback = delta_to_celsius(1.0, unit)
        lo_c = to_celsius(target_lo, unit) if target_lo is not None else target_c - fallback
        hi_c = to_celsius(target_hi, unit) if target_hi is not None else target_c + fallback
        if lo_c > hi_c:
            lo_c, hi_c = hi_c, lo_c
        # P(lo <= X <= hi) com X ~ N(forecast, sigma)
        z_hi = (forecast_temp - lo_c) / sigma
        z_lo = (forecast_temp - hi_c) / sigma
        model_prob = stats.norm.cdf(z_hi) - stats.norm.cdf(z_lo)

    else:
        return 0.0

    model_prob = max(0.0, min(1.0, model_prob))

    # Ajuste ML apenas quando há dados suficientes.
    # hour_utc = hora atual (mesma semântica do treino no settlement,
    # que usa a hora de abertura do trade — a previsão acontece no
    # momento em que o trade está sendo considerado).
    hour_now = datetime.now(timezone.utc).hour
    adjusted_prob = _ml_adjuster.adjust_probability(
        model_prob=model_prob,
        day_offset=day_offset,
        city=city,
        calibrator=_calibrator,
        hour_utc=hour_now,
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
