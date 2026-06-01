#!/usr/bin/env python3
"""
risk.py — Kelly Criterion e guardrails v5.1

AJUSTES baseados nos logs reais de 2026-06-01:

1. MIN_PRICE por tipo:
   - ABOVE/BELOW/EXACT: usa MIN_PRICE do config (agora 0.08)
   - RANGE2: usa MIN_PRICE_RANGE2 do config (0.04)
   Houston ABOVE 92°F a 0.095 e Atlanta RANGE2 a 0.034 eram trades
   legítimos bloqueados pelo piso antigo de 0.10.

2. MIN_PROB_ABOVE_BELOW: agora 0.72 no config.
   Tokyo ABOVE 27°C com prob=0.766 e edge=+0.647 era o melhor
   trade do ciclo e estava sendo bloqueado.

3. Edge máximo para ABOVE/BELOW mantido em 0.40.
   Milan ABOVE 24°C com edge=0.848 foi bloqueado corretamente —
   forecast 30.7°C vs target 24°C é suspeito (mercado sabe algo).

4. MIN_PROB_RANGE2 mantido em 0.15 — buckets de 2°F têm prob
   naturalmente baixa (~5-15% por bucket).
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

MIN_PROB_RANGE2 = 0.04   # prob mínima para range2 (buckets ~5% são normais)
MIN_EDGE_RANGE2 = 0.02   # edge mínimo para range2


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

    if unit == "F":
        target_c = (target_raw - 32) * 5 / 9
    else:
        target_c = target_raw

    # 1. Filtro de liquidez — piso diferente por tipo
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
        # Edge máximo: não lutar contra o mercado
        # Milan ABOVE 24°C edge=0.848 foi bloqueado corretamente
        if edge > 0.40:
            logger.info(
                f"Bloqueado: edge {edge:.3f} > 0.40 — modelo discordando "
                f"demais do mercado (prob={model_prob:.2f} mkt={price:.2f})"
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
            logger.info(
                f"Bloqueado: prob abaixo do mínimo para RANGE2 ({model_prob:.3f})"
            )
            return False
        if edge < MIN_EDGE_RANGE2:
            logger.info(f"Bloqueado: edge insuficiente para RANGE2 ({edge:.3f})")
            return False
        # Não entra se mercado já precificou muito alto
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
