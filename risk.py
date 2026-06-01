#!/usr/bin/env python3
"""
risk.py — Kelly Criterion e guardrails v5.2

AJUSTE v5.2:
- Edge máximo para ABOVE/BELOW: lógica diferenciada por nível de prob:
    prob >= 0.90 → cap 0.25 (prob muito alta = suspeito, mercado sabe mais)
    prob >= 0.72 → cap 0.55 (prob razoável = pode ser edge real)
  
  Antes havia cap fixo de 0.40 que bloqueava Tokyo (prob=0.766, edge=0.647).
  Tokyo forecast 29.9°C vs target 27°C com sigma=4.0 → prob=76.6% é legítimo.
  Milan forecast 30.7°C vs target 24°C → prob=95.3% é suspeito (edge=0.868 bloqueado).
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
    MIN_PRICE_RANGE2,
    MAX_PRICE,
    MAX_OPEN_TRADES,
    MAX_TOTAL_EXPOSURE,
)

logger = logging.getLogger(__name__)

MIN_PROB_RANGE2 = 0.04
MIN_EDGE_RANGE2 = 0.02


def consecutive_losses(history: list) -> int:
    count = 0
    for t in reversed(history):
        result = t.get("result")
        if result == "OPEN":
            continue
        if result == "LOSS":
            count += 1
        else:
            break
    return count


def dynamic_kelly_fraction(history: list) -> float:
    consec = consecutive_losses(history)
    if consec >= 3:
        return KELLY_FRACTION * 0.5
    if consec >= 2:
        return KELLY_FRACTION * 0.7
    return KELLY_FRACTION


def kelly_criterion(
    prob: float,
    price: float,
    balance: float = 100.0,
    fraction: float = None,
) -> float:
    if prob <= 0 or prob >= 1 or price <= 0 or price >= 1:
        return 0.0

    b = (1.0 / price) - 1.0
    q = 1.0 - prob

    kelly_pct = (prob * b - q) / b
    kelly_pct = max(0.0, kelly_pct)

    frac = fraction if fraction is not None else KELLY_FRACTION
    stake_pct = kelly_pct * frac
    stake_pct = min(stake_pct, MAX_KELLY_FRACTION_CAP)

    stake = stake_pct * balance
    stake = min(stake, MAX_POSITION)

    return round(stake, 2)


def _max_edge_for_prob(prob: float) -> float:
    """
    Cap de edge diferenciado por nível de prob.
    
    prob >= 0.90: cap 0.25
      Ex: Milan ABOVE 24°C com prob=0.953 e edge=0.868 → bloqueado (correto)
      Prob muito alta indica que o modelo está calculando algo óbvio
      que o mercado já sabe — suspeito de erro de forecast.
    
    prob >= 0.72: cap 0.55  
      Ex: Tokyo ABOVE 27°C com prob=0.766 e edge=0.647 → passa
      Prob moderada com edge alto pode ser lag do mercado em
      atualizar após nova rodada do modelo meteorológico.
    """
    if prob >= 0.90:
        return 0.25
    return 0.55


def check_guardrails(
    market: dict,
    model_prob: float,
    forecast_temp: float,
    sigma: float = None,
) -> bool:
    condition  = market.get("condition", "ABOVE").upper()
    target_raw = float(market.get("target_temp", 0))
    price      = float(market.get("price", 0))
    day_offset = int(market.get("day_offset", 1))
    unit       = market.get("unit", "C").upper()

    if unit == "F":
        target_c = (target_raw - 32) * 5 / 9
    else:
        target_c = target_raw

    # 1. Filtro de liquidez
    min_p = MIN_PRICE_RANGE2 if condition == "RANGE2" else MIN_PRICE
    if price < min_p or price > MAX_PRICE:
        logger.info(f"Bloqueado: preço fora da faixa ({price:.3f}, min={min_p})")
        return False

    edge = model_prob - price

    # 2. Lógica por tipo
    if condition in ("ABOVE", "BELOW"):
        if PROB_DEADZONE_MIN <= model_prob <= PROB_DEADZONE_MAX:
            logger.info(f"Bloqueado: prob na zona morta ({model_prob:.3f})")
            return False
        if model_prob < MIN_PROB_ABOVE_BELOW:
            logger.info(
                f"Bloqueado: prob abaixo do mínimo para {condition} "
                f"({model_prob:.3f} < {MIN_PROB_ABOVE_BELOW})"
            )
            return False
        if edge < MIN_EDGE:
            logger.info(f"Bloqueado: edge insuficiente ({edge:.3f})")
            return False

        # Edge máximo diferenciado por nível de prob
        max_edge = _max_edge_for_prob(model_prob)
        if edge > max_edge:
            logger.info(
                f"Bloqueado: edge {edge:.3f} > {max_edge} "
                f"(prob={model_prob:.2f} mkt={price:.2f})"
            )
            return False

        # Zscore mínimo
        if sigma is None or sigma <= 0:
            sigma = {1: 4.0, 2: 4.5, 3: 5.0}.get(day_offset, 5.0)
        sigma = min(sigma, SIGMA_CAP_ABOVE_BELOW)
        z_score = abs(forecast_temp - target_c) / sigma
        if z_score < MIN_TARGET_ZSCORE:
            logger.info(f"Bloqueado: zscore {z_score:.2f} < {MIN_TARGET_ZSCORE}")
            return False

    elif condition == "EXACT":
        if edge < MIN_EDGE_EXACT:
            logger.info(f"Bloqueado: edge insuficiente para EXACT ({edge:.3f})")
            return False

    elif condition == "RANGE2":
        if model_prob < MIN_PROB_RANGE2:
            logger.info(f"Bloqueado: prob abaixo do mínimo para RANGE2 ({model_prob:.3f})")
            return False
        if edge < MIN_EDGE_RANGE2:
            logger.info(f"Bloqueado: edge insuficiente para RANGE2 ({edge:.3f})")
            return False
        if price > 0.70:
            logger.info(f"Bloqueado: RANGE2 preço alto demais ({price:.3f})")
            return False

    elif condition == "RANGE":
        logger.info("Bloqueado: tipo RANGE genérico não suportado")
        return False

    else:
        logger.info(f"Bloqueado: condition desconhecida ({condition})")
        return False

    logger.info(
        f"GUARDRAIL OK: {condition} target={target_raw}°{unit} "
        f"price={price:.3f} prob={model_prob:.3f} edge={edge:+.3f}"
    )
    return True
