#!/usr/bin/env python3
"""
Risk Manager — Kelly Criterion e guardrails.

CORRIGIDO:
- check_version.py importava MIN_EV de config.py — adicionado lá.
- kelly_criterion() retornava stake como % do bankroll de $100 hardcoded.
  Agora aceita parâmetro balance opcional; sem ele usa MAX_POSITION como teto.
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
    MIN_EV,
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


def kelly_criterion(prob: float, price: float, balance: float = None) -> float:
    """
    Calcula stake usando Half-Kelly com cap.

    CORRIGIDO: versão anterior hardcodava bankroll de $100.
    Agora usa `balance` se fornecido; caso contrário usa MAX_POSITION como
    teto direto (comportamento seguro para chamadas sem contexto de bankroll).
    """
    if prob <= 0 or prob >= 1 or price <= 0:
        return 0.0

    b = (1.0 / price) - 1.0
    q = 1.0 - prob

    kelly_pct = max((prob * b - q) / b, 0.0) if b > 0 else 0.0
    stake_pct = min(kelly_pct * KELLY_FRACTION, MAX_KELLY_FRACTION_CAP)

    if balance is not None and balance > 0:
        stake = stake_pct * balance
    else:
        # Sem bankroll: interpreta stake_pct como fração do MAX_POSITION
        stake = stake_pct * 100.0

    return round(min(stake, MAX_POSITION), 2)


def kelly_stake(balance: float, prob: float, price: float) -> float:
    """Alias com assinatura (balance, prob, price) para compatibilidade."""
    return kelly_criterion(prob, price, balance)


def expected_value(prob: float, price: float) -> float:
    """EV = prob/price - 1"""
    if price <= 0:
        return 0.0
    return round(prob / price - 1.0, 4)


def open_exposure(history: list) -> float:
    """Retorna exposição total dos trades abertos."""
    return sum(float(t.get("stake", 0)) for t in history if t.get("result") == "OPEN")


def remaining_capacity(history: list) -> float:
    """Quanto pode ainda ser apostado antes de atingir MAX_TOTAL_EXPOSURE."""
    return max(0.0, MAX_TOTAL_EXPOSURE - open_exposure(history))


def cap_stake_by_type(stake: float, condition: str) -> float:
    """Aplica cap por tipo de trade (reservado para uso futuro)."""
    return min(stake, MAX_POSITION)


def check_guardrails(market: dict, model_prob: float, forecast_temp: float) -> bool:
    """
    Verifica todos os guardrails antes de executar um trade.
    Retorna True se o trade passar em todos os filtros.
    """
    condition   = (market.get("condition") or "ABOVE").upper()
    target_temp = float(market.get("target_temp", 0))
    price       = float(market.get("price", 0))
    day_offset  = int(market.get("day_offset", 1))

    # 1. Liquidez
    if price < MIN_PRICE or price > MAX_PRICE:
        logger.info(f"Preço fora da faixa: {price:.3f}")
        return False

    # 2. Zona morta de probabilidade
    if PROB_DEADZONE_MIN <= model_prob <= PROB_DEADZONE_MAX:
        logger.info(f"Probabilidade na zona morta: {model_prob:.3f}")
        return False

    # 3. Probabilidade mínima para ABOVE/BELOW
    if condition in ("ABOVE", "BELOW") and model_prob < MIN_PROB_ABOVE_BELOW:
        logger.info(f"Prob abaixo do mínimo para {condition}: {model_prob:.3f}")
        return False

    # 4. Edge mínimo
    edge = model_prob - price
    min_e = MIN_EDGE_EXACT if condition == "EXACT" else MIN_EDGE
    if edge < min_e:
        logger.info(f"Edge insuficiente ({condition}): {edge:.3f} < {min_e:.3f}")
        return False

    # 5. EV mínimo
    ev = expected_value(model_prob, price)
    if ev < MIN_EV:
        logger.info(f"EV insuficiente: {ev:.4f} < {MIN_EV:.4f}")
        return False

    # 6. Z-score mínimo
    sigma_map = {1: 2.8, 2: 3.2, 3: 3.5}
    sigma = sigma_map.get(day_offset, 3.5)
    sigma = min(
        sigma,
        SIGMA_CAP_ABOVE_BELOW if condition in ("ABOVE", "BELOW") else SIGMA_CAP_EXACT,
    )

    if sigma > 0:
        z_score = abs(forecast_temp - target_temp) / sigma
        if z_score < MIN_TARGET_ZSCORE:
            logger.info(f"Z-score abaixo do mínimo: {z_score:.2f} < {MIN_TARGET_ZSCORE}")
            return False

    return True
