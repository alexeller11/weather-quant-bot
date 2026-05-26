#!/usr/bin/env python3
"""
Weather Model - Probabilidade baseada em distribuição Normal,
com sigma calibrado por cidade e ajuste de ML online.
Versão compatível com estrutura de funções do projeto.
"""

import logging
from scipy import stats

# NOVO: calibrador e ajustador ML
from sigma_calibrator import SigmaCalibrator
from ml_adjuster import MLProbabilityAdjuster

logger = logging.getLogger(__name__)

# Instâncias globais
_calibrator = SigmaCalibrator()
_ml_adjuster = MLProbabilityAdjuster()

def get_base_sigma(day_offset: int) -> float:
    """Retorna o sigma base para o horizonte de previsão."""
    if day_offset == 1:
        return 2.8
    elif day_offset == 2:
        return 3.2
    elif day_offset == 3:
        return 3.5
    else:
        return 3.5

def calculate_probability(city: str, target_temp: float, forecast_temp: float, day_offset: int) -> float:
    """
    Retorna a probabilidade (0 a 1) de a temperatura real ser MAIOR que o target.
    Probabilidade ajustada com sigma calibrado e ML.
    """
    base_sigma = get_base_sigma(day_offset)
    sigma = _calibrator.get_adjusted_sigma(city, base_sigma)
    
    z_score = (forecast_temp - target_temp) / sigma
    model_prob = stats.norm.cdf(z_score)
    
    adjusted_prob = _ml_adjuster.adjust_probability(
        model_prob=model_prob,
        day_offset=day_offset,
        city=city,
        calibrator=_calibrator
    )
    
    logger.debug(
        f"{city} D+{day_offset}: target={target_temp}, forecast={forecast_temp}, "
        f"sigma_base={base_sigma}, sigma_adj={sigma:.2f}, "
        f"prob_raw={model_prob:.3f}, prob_adj={adjusted_prob:.3f}"
    )
    return adjusted_prob

def get_calibrator():
    """Retorna a instância global do SigmaCalibrator."""
    return _calibrator

def get_ml_adjuster():
    """Retorna a instância global do MLProbabilityAdjuster."""
    return _ml_adjuster