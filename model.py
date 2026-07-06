#!/usr/bin/env python3
"""
model.py — Probabilidade baseada em distribuição Normal

CORRIGIDO: suporte ao novo tipo "range2" (bucket de 2°F/°C da Polymarket).

CORREÇÕES (auditoria):
1. EXACT: a meia-largura do bucket agora é 0.5 na UNIDADE DO MERCADO,
   convertida para °C antes de entrar na Normal.
2. RANGE2 sem limites explícitos: fallback ±1 na unidade do mercado.
3. O sigma calibrado por cidade recebe a CONDIÇÃO do mercado.
4. O ajuste ML recebe a hora UTC atual (elimina train/serve skew).
5. AUDITORIA SENIOR: SigmaCalibrator agora é SEMPRE aplicado, mesmo
   quando sigma é passado explicitamente por forecast.py. Antes o
   calibrador coletava dados mas seus ajustes eram write-only — nunca
   lidos durante a predição. Agora: sigma de forecast.py serve como
   baseline e o calibrador adiciona o ajuste aprendido por cidade.
"""

import logging
import math
from datetime import datetime, timezone

from sigma_calibrator import SigmaCalibrator
from ml_adjuster import MLProbabilityAdjuster

logger = logging.getLogger(__name__)

_calibrator  = SigmaCalibrator()
_ml_adjuster = MLProbabilityAdjuster()


def normal_cdf(x: float) -> float:
    """CDF da Normal padrao sem depender de scipy em runtime."""
    return 0.5 * (1.0 + math.erf(float(x) / math.sqrt(2.0)))


def get_base_sigma(day_offset: int) -> float:
    """
    sigma base por horizonte — FONTE ÚNICA para todo o projeto.

    AUDITORIA bug #3: antes desta consolidacao, tres copias discordavam:
      forecast.py: {1:4,2:4.5,3:5,4:5.5,5:6}, default 6.0
      model.py:    {1:4,2:4.5,3:5},           default 6.0
      risk.py:     {1:4,2:4.5,3:5},           default 5.0   (!!)
    modelo e gate de risco aplicavam sigma diferente ao mesmo mercado.
    Tudo agora deriva desta funcao.
    """
    base = {1: 4.0, 2: 4.5, 3: 5.0, 4: 5.5, 5: 6.0}
    return base.get(int(day_offset), 6.0)


def to_celsius(value: float, unit: str) -> float:
    """Converte um VALOR ABSOLUTO de temperatura para °C."""
    if str(unit).upper() == "F":
        return (value - 32) * 5 / 9
    return value


def delta_to_celsius(delta: float, unit: str) -> float:
    """
    Converte uma DIFERENÇA/LARGURA de temperatura para °C.
    Diferente de to_celsius: largura de 0.5°F = 0.5 x 5/9 = 0.2778°C
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

    # Determina sigma base (passado ou calculado internamente)
    if sigma is None or sigma <= 0:
        sigma = get_base_sigma(day_offset)

    # SigmaCalibrator SEMPRE aplicado: adiciona ajuste aprendido por cidade/condicao
    # ao sigma base, independentemente de ele ter vindo de forecast.py ou do fallback.
    # Correcao de auditoria: antes o calibrador so executava se sigma=None,
    # tornando o aprendizado online write-only sem efeito na predicao.
    sigma = _calibrator.get_adjusted_sigma(city, sigma, condition=condition)
    if sigma <= 0:
        sigma = get_base_sigma(day_offset)

    if condition == "ABOVE":
        z = (forecast_temp - target_c) / sigma
        model_prob = normal_cdf(z)

    elif condition == "BELOW":
        z = (forecast_temp - target_c) / sigma
        model_prob = 1.0 - normal_cdf(z)

    elif condition == "EXACT":
        half = delta_to_celsius(0.5, unit)
        z_high = (forecast_temp - (target_c - half)) / sigma
        z_low  = (forecast_temp - (target_c + half)) / sigma
        model_prob = normal_cdf(z_high) - normal_cdf(z_low)

    elif condition == "RANGE2":
        fallback = delta_to_celsius(1.0, unit)
        lo_c = to_celsius(target_lo, unit) if target_lo is not None else target_c - fallback
        hi_c = to_celsius(target_hi, unit) if target_hi is not None else target_c + fallback
        if lo_c > hi_c:
            lo_c, hi_c = hi_c, lo_c
        z_hi = (forecast_temp - lo_c) / sigma
        z_lo = (forecast_temp - hi_c) / sigma
        model_prob = normal_cdf(z_hi) - normal_cdf(z_lo)

    else:
        return 0.0

    model_prob = max(0.0, min(1.0, model_prob))

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
