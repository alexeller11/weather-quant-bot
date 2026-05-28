#!/usr/bin/env python3
"""
Weather Model — Probabilidade via distribuição Normal com sigma calibrado.

CORRIGIDO:
- calculate_probability() tinha assinatura incompatível com bot.py, que
  passava (city, target_temp, forecast_temp, day_offset).
  A função aceitava exatamente esses parâmetros, mas bot.py passava
  get_forecast() como forecast_temp — que retorna uma tupla (forecast_c, sigma),
  não um float. O desempacotamento agora é feito aqui de forma defensiva.
- Adicionadas funções build_sigma() e to_celsius() que teste.py importava
  mas não existiam nesta versão do modelo.
- Mantida integração com SigmaCalibrator e MLProbabilityAdjuster.
"""

import logging
from scipy import stats

from sigma_calibrator import SigmaCalibrator
from ml_adjuster import MLProbabilityAdjuster

logger = logging.getLogger(__name__)

_calibrator  = SigmaCalibrator()
_ml_adjuster = MLProbabilityAdjuster()


# ──────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────

def get_base_sigma(day_offset: int) -> float:
    """Sigma base calibrado pelo erro real observado nos 26 trades."""
    return {1: 2.8, 2: 3.2, 3: 3.5}.get(day_offset, 4.5)


def to_celsius(value: float, unit: str) -> float:
    """
    Converte valor para Celsius.
    ADICIONADO: usado em teste.py para calcular zscore em unidade comum.
    """
    unit = (unit or "C").upper().strip()
    if unit == "F":
        return (value - 32) * 5 / 9
    return float(value)


def build_sigma(city_slug: str, forecast_day: int, raw_sigma: float,
                condition: str) -> float | None:
    """
    Constrói sigma final com cap por condição.
    Retorna None se sigma exceder o cap (bloqueio de trade).

    ADICIONADO: usado em teste.py e check_version.py — existia na versão
    anterior do modelo mas foi removido na reescrita.
    """
    from config import SIGMA_CAP_ABOVE_BELOW, SIGMA_CAP_EXACT

    condition = (condition or "ABOVE").upper()
    cap = SIGMA_CAP_ABOVE_BELOW if condition in ("ABOVE", "BELOW") else SIGMA_CAP_EXACT

    if raw_sigma > cap:
        logger.debug(
            f"build_sigma bloqueado: {city_slug} d{forecast_day} "
            f"sigma={raw_sigma:.2f} > cap={cap:.2f} ({condition})"
        )
        return None

    # Ajuste do calibrador (aprende com erros históricos)
    adjusted = _calibrator.get_adjusted_sigma(city_slug, raw_sigma)
    return round(min(adjusted, cap), 4)


# ──────────────────────────────────────────────────────────────
# FUNÇÃO PRINCIPAL
# ──────────────────────────────────────────────────────────────

def calculate_probability(
    city: str,
    target_temp: float,
    forecast_temp,          # float OU tupla (forecast_c, sigma) de get_forecast()
    day_offset: int,
    condition: str = "ABOVE",
    unit: str = "C",
) -> float:
    """
    Retorna probabilidade (0–1) de a temperatura real satisfazer a condição.

    CORRIGIDO: bot.py chama get_forecast() e passa o retorno diretamente
    como forecast_temp. get_forecast() retorna (forecast_c, sigma), não um
    float. O desempacotamento defensivo aqui evita que o bug silencioso
    retorne prob ≈ 1.0 ao interpretar a tupla como número.

    Aceita:
      forecast_temp = 28.5            (float — uso direto)
      forecast_temp = (28.5, 3.2)     (tupla de get_forecast())
    """
    # Desempacotamento defensivo da tupla de get_forecast()
    raw_sigma_from_forecast = None
    if isinstance(forecast_temp, (tuple, list)):
        if len(forecast_temp) >= 2:
            forecast_c, raw_sigma_from_forecast = forecast_temp[0], forecast_temp[1]
        else:
            forecast_c = forecast_temp[0]
        forecast_temp = forecast_c

    if forecast_temp is None:
        logger.warning(f"calculate_probability: forecast_temp é None para {city}")
        return 0.5

    forecast_temp = float(forecast_temp)
    target_temp   = float(target_temp)

    # Sigma: usa o retornado pelo forecast se disponível, senão base por dia
    base_sigma = raw_sigma_from_forecast if raw_sigma_from_forecast else get_base_sigma(day_offset)
    sigma = _calibrator.get_adjusted_sigma(city, base_sigma)
    sigma = max(sigma, 0.1)  # floor para evitar divisão por zero

    # Converte para mesma unidade antes de calcular zscore
    target_c   = to_celsius(target_temp, unit)
    forecast_c = to_celsius(forecast_temp, unit) if unit.upper() == "F" else forecast_temp

    z_score = (forecast_c - target_c) / sigma

    condition = (condition or "ABOVE").upper()
    if condition == "ABOVE":
        model_prob = float(stats.norm.cdf(z_score))
    elif condition == "BELOW":
        model_prob = float(1 - stats.norm.cdf(z_score))
    else:
        # EXACT: probabilidade de cair dentro de ±0.5°C
        model_prob = float(
            stats.norm.cdf((forecast_c - target_c + 0.5) / sigma) -
            stats.norm.cdf((forecast_c - target_c - 0.5) / sigma)
        )

    # Ajuste ML (só aplica se houver dados suficientes)
    adjusted_prob = _ml_adjuster.adjust_probability(
        model_prob=model_prob,
        day_offset=day_offset,
        city=city,
        calibrator=_calibrator,
    )

    logger.debug(
        f"{city} D+{day_offset} {condition}: "
        f"target={target_c:.1f}C forecast={forecast_c:.1f}C "
        f"sigma={sigma:.2f} z={z_score:.2f} "
        f"prob_raw={model_prob:.3f} prob_adj={adjusted_prob:.3f}"
    )

    return round(adjusted_prob, 4)


def get_calibrator():
    return _calibrator


def get_ml_adjuster():
    return _ml_adjuster
