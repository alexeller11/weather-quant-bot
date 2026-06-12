#!/usr/bin/env python3
"""
risk.py — Kelly Criterion e guardrails v5.4

v5.4: Suporte a apostas NO (vender YES)
- check_guardrails() agora aceita side="YES" (padrão) ou side="NO"
- Para NO: lógica invertida — apostamos quando mercado paga muito por algo improvável
- NO edge = price_yes - prob_yes  (mercado superestima a prob)
- Requer: NO edge >= MIN_EDGE_NO, prob_yes <= MAX_PROB_FOR_NO
- Kelly para NO: b = (1/price_no) - 1 = (1/(1-price_yes)) - 1

CORREÇÕES (auditoria):
1. FEE_RATE (2%) agora entra no Kelly e no EV. O settlement desconta
   2% do payout bruto na vitória, então o ganho líquido por $1 apostado
   é b_eff = (1-FEE)/price - 1, e não (1/price) - 1. Ignorar a fee
   superestimava b e o EV, gerando overbetting sistemático e aprovando
   trades cujo EV líquido real era negativo na margem.
2. MIN_EV (config) agora é APLICADO: trades com EV líquido por $1
   apostado abaixo de MIN_EV são bloqueados. A constante existia em
   config.py e nunca era usada em lugar nenhum.
3. Novos helpers de exposição usados pelo bot:
   - exposure_headroom(): quanto AINDA cabe sem estourar MAX_TOTAL_EXPOSURE
     (o check antigo `exposure >= MAX` antes do trade deixava ultrapassar
     o teto em até +MAX_POSITION).
   - event_open_stake() + MAX_EVENT_EXPOSURE: limite de stake somado em
     buckets do MESMO evento (cidade+dia), que são mutuamente exclusivos
     e correlacionados — antes era possível abrir N posições YES no mesmo
     evento em que no máximo UMA pode vencer.
"""

import os
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
    MIN_PRICE_RANGE2,
    MAX_PRICE,
    MAX_OPEN_TRADES,
    MAX_TOTAL_EXPOSURE,
)

logger = logging.getLogger(__name__)

MIN_PROB_RANGE2 = 0.04
MIN_EDGE_RANGE2 = 0.02

# Parâmetros para apostas NO
MIN_EDGE_NO       = 0.15   # edge mínimo para NO (price_yes - prob_yes)
MAX_PROB_FOR_NO   = 0.35   # só apostar NO se modelo diz prob_yes <= 35%
MIN_PRICE_YES_FOR_NO = 0.55  # só apostar NO se mercado paga >= 55% para YES

# Fee de liquidação aplicada pelo settlement sobre o payout bruto na vitória.
# Precisa ser idêntica à usada em settlement.py (que importa daqui).
FEE_RATE = 0.02

# Limite de stake somado por EVENTO (mesma cidade + mesma data de mercado).
# Buckets do mesmo evento são mutuamente exclusivos: por padrão permitimos
# no máximo o equivalente a UMA posição cheia por evento.
MAX_EVENT_EXPOSURE = float(os.getenv("MAX_EVENT_EXPOSURE", str(MAX_POSITION)))


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


def _net_odds(price: float) -> float:
    """
    Ganho líquido por $1 apostado, já descontando a fee do settlement.
    shares = stake/price; payout bruto na vitória = shares × $1;
    líquido = bruto × (1 - FEE_RATE). Logo b_eff = (1-FEE)/price - 1.
    """
    return (1.0 - FEE_RATE) / price - 1.0


def expected_value(prob: float, price: float) -> float:
    """
    EV líquido por $1 apostado (fee incluída):
        EV = prob × b_eff − (1 − prob)
    """
    if price <= 0 or price >= 1:
        return -1.0
    b = _net_odds(price)
    return prob * b - (1.0 - prob)


def expected_value_no(model_prob_yes: float, price_yes: float) -> float:
    """EV líquido por $1 apostado no lado NO (fee incluída)."""
    return expected_value(1.0 - model_prob_yes, 1.0 - price_yes)


def kelly_criterion(
    prob: float,
    price: float,
    balance: float = 100.0,
    fraction: float = None,
) -> float:
    if prob <= 0 or prob >= 1 or price <= 0 or price >= 1:
        return 0.0

    # Odds líquidas (com fee). Antes usava (1/price - 1), superestimando
    # o ganho na vitória e, portanto, a fração de Kelly.
    b = _net_odds(price)
    if b <= 0:
        return 0.0
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
    if prob >= 0.90:
        return 0.25
    return 0.70


def check_guardrails(
    market: dict,
    model_prob: float,
    forecast_temp: float,
    sigma: float = None,
    side: str = "YES",
) -> bool:
    """
    side="YES": aposta normal (comprar YES)
    side="NO":  aposta invertida (comprar NO, equivale a vender YES)
    """
    condition  = market.get("condition", "ABOVE").upper()
    target_raw = float(market.get("target_temp", 0))
    price_yes  = float(market.get("price", 0))
    day_offset = int(market.get("day_offset", 1))
    unit       = market.get("unit", "C").upper()

    if unit == "F":
        target_c = (target_raw - 32) * 5 / 9
    else:
        target_c = target_raw

    # === LÓGICA NO ===
    if side == "NO":
        return _check_no_guardrails(condition, price_yes, model_prob)

    # === LÓGICA YES (original) ===
    min_p = MIN_PRICE_RANGE2 if condition == "RANGE2" else MIN_PRICE
    if price_yes < min_p or price_yes > MAX_PRICE:
        logger.info(f"Bloqueado: preço fora da faixa ({price_yes:.3f}, min={min_p})")
        return False

    edge = model_prob - price_yes

    # EV líquido mínimo (fee incluída) — vale para todas as condições.
    ev = expected_value(model_prob, price_yes)
    if ev < MIN_EV:
        logger.info(
            f"Bloqueado: EV líquido insuficiente ({ev:+.3f} < {MIN_EV}) "
            f"[prob={model_prob:.3f} price={price_yes:.3f} fee={FEE_RATE}]"
        )
        return False

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

        max_edge = _max_edge_for_prob(model_prob)
        if edge > max_edge:
            logger.info(
                f"Bloqueado: edge {edge:.3f} > {max_edge} "
                f"(prob={model_prob:.2f} mkt={price_yes:.2f})"
            )
            return False

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
        if price_yes > 0.70:
            logger.info(f"Bloqueado: RANGE2 preço alto demais ({price_yes:.3f})")
            return False

    elif condition == "RANGE":
        logger.info("Bloqueado: tipo RANGE genérico não suportado")
        return False

    else:
        logger.info(f"Bloqueado: condition desconhecida ({condition})")
        return False

    logger.info(
        f"GUARDRAIL OK [{side}]: {condition} target={target_raw}°{unit} "
        f"price_yes={price_yes:.3f} prob={model_prob:.3f} edge={edge:+.3f} EV={ev:+.3f}"
    )
    return True


def _check_no_guardrails(condition: str, price_yes: float, model_prob: float) -> bool:
    """
    Guardrails para apostas NO.

    Lógica: apostamos NO quando o mercado paga muito para YES (price_yes alto)
    mas o modelo estima que a prob de YES é baixa.

    NO edge = price_yes - model_prob
    Exemplos do log:
      Toronto ABOVE 28°C: mkt=0.725, model=0.212 → NO edge = 0.513
      Miami BELOW 85°F:   mkt=0.914, model=0.230 → NO edge = 0.684
    """
    # Só ABOVE, BELOW e EXACT — RANGE2 tem lógica diferente
    if condition not in ("ABOVE", "BELOW", "EXACT"):
        logger.info(f"NO não suportado para {condition}")
        return False

    # Mercado precisa estar apostando alto em YES
    if price_yes < MIN_PRICE_YES_FOR_NO:
        logger.info(f"NO bloqueado: price_yes muito baixo ({price_yes:.3f} < {MIN_PRICE_YES_FOR_NO})")
        return False

    # Modelo precisa discordar — prob baixa
    if model_prob > MAX_PROB_FOR_NO:
        logger.info(f"NO bloqueado: model_prob alta demais ({model_prob:.3f} > {MAX_PROB_FOR_NO})")
        return False

    # Edge NO = quanto o mercado está pagando a mais
    no_edge = price_yes - model_prob
    if no_edge < MIN_EDGE_NO:
        logger.info(f"NO bloqueado: edge insuficiente ({no_edge:.3f} < {MIN_EDGE_NO})")
        return False

    # Preço NO = 1 - price_yes; precisa ter liquidez mínima
    price_no = 1.0 - price_yes
    if price_no < MIN_PRICE:
        logger.info(f"NO bloqueado: price_no muito baixo ({price_no:.3f})")
        return False

    # EV líquido mínimo do lado NO (fee incluída)
    ev_no = expected_value_no(model_prob, price_yes)
    if ev_no < MIN_EV:
        logger.info(
            f"NO bloqueado: EV líquido insuficiente ({ev_no:+.3f} < {MIN_EV})"
        )
        return False

    logger.info(
        f"GUARDRAIL OK [NO]: {condition} price_yes={price_yes:.3f} "
        f"price_no={price_no:.3f} prob={model_prob:.3f} NO_edge={no_edge:+.3f} EV={ev_no:+.3f}"
    )
    return True


def kelly_criterion_no(
    model_prob_yes: float,
    price_yes: float,
    balance: float = 100.0,
    fraction: float = None,
) -> float:
    """
    Kelly para apostar NO (comprar NO a price_no = 1 - price_yes).
    prob_no = 1 - model_prob_yes
    price_no = 1 - price_yes
    """
    prob_no  = 1.0 - model_prob_yes
    price_no = 1.0 - price_yes

    if prob_no <= 0 or prob_no >= 1 or price_no <= 0 or price_no >= 1:
        return 0.0

    # Odds líquidas (com fee) — mesma correção do kelly_criterion.
    b = _net_odds(price_no)
    if b <= 0:
        return 0.0
    q = 1.0 - prob_no  # = model_prob_yes

    kelly_pct = (prob_no * b - q) / b
    kelly_pct = max(0.0, kelly_pct)

    frac = fraction if fraction is not None else KELLY_FRACTION
    stake_pct = kelly_pct * frac
    stake_pct = min(stake_pct, MAX_KELLY_FRACTION_CAP)

    stake = stake_pct * balance
    stake = min(stake, MAX_POSITION)

    return round(stake, 2)


# ── Exposição: helpers usados pelo bot ───────────────────────────────

def exposure_headroom(current_exposure: float) -> float:
    """
    Quanto de stake ainda CABE sem ultrapassar MAX_TOTAL_EXPOSURE.
    O bot deve clampar o stake a este valor (e descartar se <= 0).
    """
    return max(0.0, MAX_TOTAL_EXPOSURE - max(0.0, current_exposure))


def event_open_stake(open_trades: list, city: str, market_date: str) -> float:
    """
    Soma do stake já aberto em buckets do MESMO evento
    (mesma cidade normalizada + mesma data de mercado).
    """
    city_key = (city or "").strip().lower()
    total = 0.0
    for t in open_trades or []:
        if (t.get("city", "") or "").strip().lower() != city_key:
            continue
        if str(t.get("market_date", "")) != str(market_date):
            continue
        try:
            total += float(t.get("stake", 0) or 0)
        except (TypeError, ValueError):
            continue
    return total


def event_headroom(open_trades: list, city: str, market_date: str) -> float:
    """
    Quanto de stake ainda cabe NESTE evento (cidade+dia) sem ultrapassar
    MAX_EVENT_EXPOSURE. Buckets do mesmo evento são mutuamente exclusivos.
    """
    used = event_open_stake(open_trades, city, market_date)
    return max(0.0, MAX_EVENT_EXPOSURE - used)
