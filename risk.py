#!/usr/bin/env python3
"""
Risk Manager - Kelly Criterion e guardrails.
"""

import logging
from config import (
    KELLY_FRACTION,
    MAX_KELLY_FRACTION_CAP,
    MAX_POSITION,
    MIN_PROB_ABOVE_BELOW,
    MIN_TARGET_ZSCORE,
    MIN_EDGE,
    MIN_EDGE_EXACT,
    SIGMA_CAP_ABOVE_BELOW,
    SIGMA_CAP_EXACT,
    PROB_DEADZONE_MIN,
    PROB_DEADZONE_MAX,
    MIN_PRICE,
    MAX_PRICE,
    MAX_OPEN_TRADES,
    MAX_TOTAL_EXPOSURE
)

logger = logging.getLogger(__name__)


def kelly_criterion(prob: float, price: float) -> float:
    """
    Calcula o stake usando Half-Kelly com cap.
    """
    if prob <= 0 or prob >= 1:
        return 0.0
    
    b = (1.0 / price) - 1.0  # odds
    q = 1.0 - prob
    
    kelly_pct = (prob * b - q) / b
    kelly_pct = max(0.0, kelly_pct)
    
    # Aplica fração Kelly e cap
    stake_pct = kelly_pct * KELLY_FRACTION
    stake_pct = min(stake_pct, MAX_KELLY_FRACTION_CAP)
    
    # Converte para valor absoluto com cap
    stake = stake_pct * 100.0  # assumindo bankroll de $100
    stake = min(stake, MAX_POSITION)
    
    return round(stake, 2)


def check_guardrails(market: dict, model_prob: float, forecast_temp: float) -> bool:
    """
    Verifica todos os guardrails antes de executar um trade.
    Retorna True se o trade passar em todos os filtros.
    """
    condition = market.get('condition', '')
    target_temp = market.get('target_temp', 0)
    price = market.get('price', 0)
    day_offset = market.get('day_offset', 1)
    
    # 1. Filtro de liquidez
    if price < MIN_PRICE or price > MAX_PRICE:
        logger.info(f"🚫 Preço fora da faixa de liquidez: {price}")
        return False
    
    # 2. Zona morta de probabilidade
    if PROB_DEADZONE_MIN <= model_prob <= PROB_DEADZONE_MAX:
        logger.info(f"🚫 Probabilidade na zona morta: {model_prob:.3f}")
        return False
    
    # 3. Probabilidade mínima para ABOVE/BELOW
    if condition in ('ABOVE', 'BELOW'):
        if model_prob < MIN_PROB_ABOVE_BELOW:
            logger.info(f"🚫 Probabilidade abaixo do mínimo para {condition}: {model_prob:.3f}")
            return False
    
    # 4. Edge mínimo
    edge = model_prob - price
    if condition == 'EXACT':
        if edge < MIN_EDGE_EXACT:
            logger.info(f"🚫 Edge insuficiente para EXACT: {edge:.3f}")
            return False
    else:
        if edge < MIN_EDGE:
            logger.info(f"🚫 Edge insuficiente: {edge:.3f}")
            return False
    
    # 5. Z-score mínimo
    sigma_map = {1: 2.8, 2: 3.2, 3: 3.5}
    sigma = sigma_map.get(day_offset, 3.5)
    
    if condition in ('ABOVE', 'BELOW'):
        sigma = min(sigma, SIGMA_CAP_ABOVE_BELOW)
    else:
        sigma = min(sigma, SIGMA_CAP_EXACT)
    
    z_score = abs(forecast_temp - target_temp) / sigma
    
    if z_score < MIN_TARGET_ZSCORE:
        logger.info(f"🚫 Z-score abaixo do mínimo: {z_score:.2f}")
        return False
    
    return True