#!/usr/bin/env python3
"""
Risk Manager — Kelly Criterion e guardrails.

CORRIGIDO v4:
- check_guardrails(): MIN_PRICE agora vem do config (0.10) em vez de
  hardcoded, para refletir a mudança no config.py.
- Adicionado log detalhado do yes_price e target quando um mercado
  passa todos os guardrails — facilita auditoria do que está entrando.
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

    if condition == "RANGE":
        logger.info("Bloqueado: tipo RANGE não suportado pelo modelo")
        return False

    if unit == "F":
        target_c = (target_raw - 32) * 5 / 9
    else:
        target_c = target_raw

    # 1. Filtro de liquidez (usa MIN_PRICE do config — agora 0.10)
    if price < MIN_PRICE or price > MAX_PRICE:
        logger.info(f"Bloqueado: preço fora da faixa de liquidez ({price:.3f})")
        return False

    # 2. Zona morta e prob mínima (apenas ABOVE/BELOW)
    if condition in ("ABOVE", "BELOW"):
        if PROB_DEADZONE_MIN <= model_prob <= PROB_DEADZONE_MAX:
            logger.info(f"Bloqueado: prob na zona morta ({model_prob:.3f})")
            return False

        if model_prob < MIN_PROB_ABOVE_BELOW:
            logger.info(f"Bloqueado: prob abaixo do mínimo para {condition} ({model_prob:.3f})")
            return False

    # 3. Edge mínimo por tipo
    edge = model_prob - price
    if condition == "EXACT":
        if edge < MIN_EDGE_EXACT:
            logger.info(f"Bloqueado: edge insuficiente para EXACT ({edge:.3f})")
            return False
    else:
        if edge < MIN_EDGE:
            logger.info(f"Bloqueado: edge insuficiente ({edge:.3f})")
            return False

    # 4. Sanidade: não lutar contra o mercado
    if edge > 0.40:
        logger.info(
            f"Bloqueado: edge {edge:.3f} > 0.40 — modelo discordando demais "
            f"do mercado (modelo:{model_prob:.2f} mercado:{price:.2f})."
        )
        return False

    # 5. Zscore mínimo — apenas ABOVE/BELOW
    if condition in ("ABOVE", "BELOW"):
        if sigma is None or sigma <= 0:
            sigma_map = {1: 4.0, 2: 4.5, 3: 5.0}
            sigma = sigma_map.get(day_offset, 5.0)
        sigma = min(sigma, SIGMA_CAP_ABOVE_BELOW)

        z_score = abs(forecast_temp - target_c) / sigma
        if z_score < MIN_TARGET_ZSCORE:
            logger.info(f"Bloqueado: zscore abaixo do mínimo ({z_score:.2f} < {MIN_TARGET_ZSCORE})")
            return False

    # PASSADO: log detalhado para auditoria
    logger.info(
        f"GUARDRAIL OK: {condition} target={target_raw}°{unit} "
        f"price={price:.3f} prob={model_prob:.3f} "
        f"edge={edge:.3f} forecast={forecast_temp:.1f}°C"
    )
    return True
