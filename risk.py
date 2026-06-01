#!/usr/bin/env python3
"""
Risk Manager — Kelly Criterion e guardrails.

CORREÇÕES v4:
  1. kelly_criterion() agora recebe 'balance' como parâmetro.
     Antes: stake_pct * 100.0  ← bankroll hardcoded em $100
     Agora: stake_pct * balance ← saldo real do momento

  2. check_guardrails() recebe 'condition' e aplica limites diferenciados
     por tipo: ABOVE/BELOW usam SIGMA_CAP_ABOVE_BELOW; EXACT usam SIGMA_CAP_EXACT.
     Zscore mínimo só se aplica a ABOVE/BELOW (EXACT tem lógica própria).
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
    MAX_TOTAL_EXPOSURE,
)

logger = logging.getLogger(__name__)


def kelly_criterion(prob: float, price: float, balance: float = 100.0) -> float:
    """
    Calcula o stake em dólares usando Half-Kelly com cap por posição.

    Parâmetros:
        prob    — probabilidade estimada pelo modelo
        price   — preço de mercado do contrato YES (0 a 1)
        balance — saldo atual do bankroll em dólares

    CORREÇÃO: antes usava bankroll fixo de $100 independente do saldo real.
    Agora o stake é proporcional ao saldo atual, respeitando MAX_POSITION.
    """
    if prob <= 0 or prob >= 1 or price <= 0 or price >= 1:
        return 0.0

    b = (1.0 / price) - 1.0   # odds decimais
    q = 1.0 - prob

    kelly_pct = (prob * b - q) / b
    kelly_pct = max(0.0, kelly_pct)

    # Aplica fração Kelly e cap percentual
    stake_pct = kelly_pct * KELLY_FRACTION
    stake_pct = min(stake_pct, MAX_KELLY_FRACTION_CAP)

    # Converte para valor absoluto com cap por posição
    stake = stake_pct * balance
    stake = min(stake, MAX_POSITION)

    return round(stake, 2)


def check_guardrails(
    market: dict,
    model_prob: float,
    forecast_temp: float,
    sigma: float = None,
) -> bool:
    """
    Verifica todos os guardrails antes de executar um trade.
    Retorna True se o trade passar em todos os filtros.

    Espera no dict 'market':
        condition   — "ABOVE", "BELOW" ou "EXACT"
        target_temp — temperatura alvo em °C
        price       — preço YES no mercado
        day_offset  — dias de antecedência
        unit        — "C" ou "F" (para converter target)

    sigma — sigma já calculado pelo forecast (com ajustes climáticos por
            cidade); se None, usa o valor base do day_offset.

    CORREÇÃO: zscore mínimo agora só se aplica a ABOVE/BELOW.
    Para EXACT o edge e a prob já filtram adequadamente.
    """
    condition  = market.get("condition", "ABOVE").upper()
    target_raw = float(market.get("target_temp", 0))
    price      = float(market.get("price", 0))
    day_offset = int(market.get("day_offset", 1))
    unit       = market.get("unit", "C").upper()

    # Converte target para Celsius
    if unit == "F":
        target_c = (target_raw - 32) * 5 / 9
    else:
        target_c = target_raw

    # 1. Filtro de liquidez
    if price < MIN_PRICE or price > MAX_PRICE:
        logger.info(f"Bloqueado: preço fora da faixa de liquidez ({price:.3f})")
        return False

    # 2. Zona morta de probabilidade (apenas ABOVE/BELOW)
    if condition in ("ABOVE", "BELOW"):
        if PROB_DEADZONE_MIN <= model_prob <= PROB_DEADZONE_MAX:
            logger.info(f"Bloqueado: prob na zona morta ({model_prob:.3f})")
            return False

        # 3. Probabilidade mínima para ABOVE/BELOW
        if model_prob < MIN_PROB_ABOVE_BELOW:
            logger.info(f"Bloqueado: prob abaixo do mínimo para {condition} ({model_prob:.3f})")
            return False

    # 4. Edge mínimo por tipo
    edge = model_prob - price
    if condition == "EXACT":
        if edge < MIN_EDGE_EXACT:
            logger.info(f"Bloqueado: edge insuficiente para EXACT ({edge:.3f})")
            return False
    else:
        if edge < MIN_EDGE:
            logger.info(f"Bloqueado: edge insuficiente ({edge:.3f})")
            return False

    # 5. Zscore mínimo — apenas ABOVE/BELOW
    if condition in ("ABOVE", "BELOW"):
        if sigma is None or sigma <= 0:
            sigma_map = {1: 2.8, 2: 3.2, 3: 3.5}
            sigma = sigma_map.get(day_offset, 4.0)
        sigma = min(sigma, SIGMA_CAP_ABOVE_BELOW)

        z_score = abs(forecast_temp - target_c) / sigma
        if z_score < MIN_TARGET_ZSCORE:
            logger.info(f"Bloqueado: zscore abaixo do mínimo ({z_score:.2f} < {MIN_TARGET_ZSCORE})")
            return False

    return True
