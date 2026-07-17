#!/usr/bin/env python3
"""
risk.py — Kelly Criterion e guardrails v5.5

v5.4: Suporte a apostas NO (vender YES)

CORREÇÕES (auditoria):
1. FEE_RATE (2%) entra no Kelly e no EV.
2. MIN_EV agora é aplicado.
3. exposure_headroom() e event_headroom(): helpers para o bot.

AUDITORIA SENIOR:
4. _check_no_guardrails agora recebe forecast_temp, target_c, sigma e
   day_offset e aplica zscore check identico ao lado YES. Antes era
   possivel entrar NO quando o forecast estava exatamente no target,
   onde a incerteza e maxima e o edge pode ser espurio.

AJUSTE v5.5 (2026-06-17):
5. MIN_PRICE_YES_FOR_NO: 0.55 → 0.45
   Mercados EXACT atuais têm distribuição espalhada (35-45% por bucket),
   nenhum passa 0.55. Baixar para 0.45 abre Madrid, Milan, Mexico City
   mantendo proteção contra mercados onde YES já decidiu (>45%).
6. Suporte a NO para RANGE2: adicionado.
   A lógica é idêntica ao EXACT — apostamos que a temperatura NÃO cai
   no bucket. O zscore check garante que o forecast está suficientemente
   distante do bucket antes de entrar.

PATCH (correção aplicada nesta versão):
7. kelly_criterion(): o parâmetro se chamava 'model_prob' mas o corpo da
   função referenciava a variável inexistente 'prob' em três lugares
   ('if prob <= 0...', 'q = 1.0 - prob', 'kelly_pct = (prob * b - q) / b').
   Isso causava NameError em TODA chamada da função — ou seja, nenhum
   trade do lado YES conseguia ter o stake calculado. Corrigido para usar
   'model_prob' consistentemente.
"""

import os
import logging
import time
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

from analytics.storage import load_health

logger = logging.getLogger(__name__)

MIN_PROB_RANGE2 = 0.04
MIN_EDGE_RANGE2 = 0.02

# Parâmetros para apostas NO
MIN_EDGE_NO          = 0.15
MAX_PROB_FOR_NO      = 0.35

# AJUSTE v5.5: 0.55 → 0.45
# Mercados EXACT atuais têm distribuição espalhada; nenhum bucket
# individual passa 0.55. Com 0.45 abrimos mercados válidos mantendo
# proteção contra YES já decidido.
MIN_PRICE_YES_FOR_NO = float(os.getenv("MIN_PRICE_YES_FOR_NO", "0.45"))

# Fee de liquidação — deve ser idêntica à usada em settlement.py.
FEE_RATE = 0.02

# Limite de stake por EVENTO (cidade + data).
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
    """Ganho líquido por $1 apostado descontando a fee."""
    return (1.0 - FEE_RATE) / price - 1.0


def expected_value(prob: float, price: float) -> float:
    """EV líquido por $1 apostado (fee incluída)."""
    if price <= 0 or price >= 1:
        return -1.0
    b = _net_odds(price)
    return prob * b - (1.0 - prob)


def expected_value_no(model_prob_yes: float, price_yes: float) -> float:
    """EV líquido por $1 apostado no lado NO (fee incluída)."""
    return expected_value(1.0 - model_prob_yes, 1.0 - price_yes)


def kelly_criterion(
    model_prob: float,
    price: float,
    balance: float = 100.0,
    fraction: float = None,
    city: str = None,
) -> float:
    # PATCH 7: era 'prob' (indefinido) -> 'model_prob' (nome real do parâmetro).
    if model_prob <= 0 or model_prob >= 1 or price <= 0 or price >= 1:
        return 0.0

    b = _net_odds(price)
    if b <= 0:
        return 0.0
    q = 1.0 - model_prob

    kelly_pct = (model_prob * b - q) / b
    kelly_pct = max(0.0, kelly_pct)

    frac = fraction if fraction is not None else KELLY_FRACTION

    # Ajuste por Health Factor (Score de performance) v5.8
    stake_adj, reason = apply_health_factor(1.0, city=city)
    frac = frac * stake_adj
    if stake_adj < 1.0:
        logger.info(f"Kelly ajustado por saúde: {reason}")

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
) -> tuple:
    """
    Retorna (bool ok, str reason).
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
        return _check_no_guardrails(
            condition, price_yes, model_prob,
            forecast_temp=forecast_temp,
            target_c=target_c,
            sigma=sigma,
            day_offset=day_offset,
        )

    # === LÓGICA YES ===
    min_p = MIN_PRICE_RANGE2 if condition == "RANGE2" else MIN_PRICE
    if price_yes < min_p or price_yes > MAX_PRICE:
        return False, "preco_fora_da_faixa"

    edge = model_prob - price_yes

    ev = expected_value(model_prob, price_yes)
    if ev < MIN_EV:
        return False, "ev_insuficiente"

    if condition in ("ABOVE", "BELOW"):
        if PROB_DEADZONE_MIN <= model_prob <= PROB_DEADZONE_MAX:
            return False, "zona_morta"
        if model_prob < MIN_PROB_ABOVE_BELOW:
            return False, "prob_baixa"
        if edge < MIN_EDGE:
            return False, "edge_insuficiente"

        max_edge = _max_edge_for_prob(model_prob)
        if edge > max_edge:
            return False, "edge_alto_demais"

        if sigma is None or sigma <= 0:
            sigma = {1: 4.0, 2: 4.5, 3: 5.0}.get(day_offset, 5.0)
        sigma = min(sigma, SIGMA_CAP_ABOVE_BELOW)
        z_score = abs(forecast_temp - target_c) / sigma
        if z_score < MIN_TARGET_ZSCORE:
            return False, "zscore_baixo"

    elif condition == "EXACT":
        if edge < MIN_EDGE_EXACT:
            return False, "edge_insuficiente"

    elif condition == "RANGE2":
        if model_prob < MIN_PROB_RANGE2:
            return False, "prob_baixa"
        if edge < MIN_EDGE_RANGE2:
            return False, "edge_insuficiente"
        if price_yes > 0.70:
            return False, "preco_alto"

    elif condition == "RANGE":
        return False, "tipo_nao_suportado"

    else:
        return False, "condicao_desconhecida"

    return True, "ok"


def _check_no_guardrails(
    condition: str,
    price_yes: float,
    model_prob: float,
    forecast_temp: float = None,
    target_c: float = None,
    sigma: float = None,
    day_offset: int = 1,
) -> tuple:
    """
    Guardrails para apostas NO.
    Retorna (bool ok, str reason).
    """
    if condition not in ("ABOVE", "BELOW", "EXACT", "RANGE2"):
        return False, "condicao_nao_suportada"

    if price_yes < MIN_PRICE_YES_FOR_NO:
        return False, "price_yes_baixo"

    if model_prob > MAX_PROB_FOR_NO:
        return False, "prob_alta"

    no_edge = price_yes - model_prob
    if no_edge < MIN_EDGE_NO:
        return False, "edge_insuficiente"

    price_no = 1.0 - price_yes
    if price_no < MIN_PRICE:
        return False, "price_no_baixo"

    ev_no = expected_value_no(model_prob, price_yes)
    if ev_no < MIN_EV:
        return False, "ev_insuficiente"

    # Zscore check
    if forecast_temp is not None and target_c is not None:
        eff_sigma = sigma if (sigma and sigma > 0) else {1: 4.0, 2: 4.5, 3: 5.0}.get(day_offset, 5.0)
        eff_sigma = min(eff_sigma, SIGMA_CAP_ABOVE_BELOW)
        z_score = abs(forecast_temp - target_c) / eff_sigma
        if z_score < MIN_TARGET_ZSCORE:
            return False, "zscore_baixo"

    return True, "ok"


def kelly_criterion_no(
    model_prob_yes: float,
    price_yes: float,
    balance: float = 100.0,
    fraction: float = None,
) -> float:
    prob_no  = 1.0 - model_prob_yes
    price_no = 1.0 - price_yes

    if prob_no <= 0 or prob_no >= 1 or price_no <= 0 or price_no >= 1:
        return 0.0

    b = _net_odds(price_no)
    if b <= 0:
        return 0.0
    q = 1.0 - prob_no

    kelly_pct = (prob_no * b - q) / b
    kelly_pct = max(0.0, kelly_pct)

    frac = fraction if fraction is not None else KELLY_FRACTION

    # Ajuste por Health Factor (Score de performance)
    # Nota: No v5.8 o city_slug é passado para permitir boosts específicos
    stake_adj, reason = apply_health_factor(1.0) # City pass-through via wrapper se necessário
    frac = frac * stake_adj
    if stake_adj < 1.0:
        logger.info(f"Kelly NO ajustado por saúde: {reason}")

    stake_pct = kelly_pct * frac
    stake_pct = min(stake_pct, MAX_KELLY_FRACTION_CAP)

    stake = stake_pct * balance
    stake = min(stake, MAX_POSITION)

    return round(stake, 2)


# ── Exposição: helpers usados pelo bot ────────────────────────────────────

def exposure_headroom(current_exposure: float) -> float:
    return max(0.0, MAX_TOTAL_EXPOSURE - max(0.0, current_exposure))


def event_open_stake(open_trades: list, city: str, market_date: str) -> float:
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
    used = event_open_stake(open_trades, city, market_date)
    return max(0.0, MAX_EVENT_EXPOSURE - used)


# ── Cooldown após perdas consecutivas ────────────────────────────

def city_trading_cooldown(history: list, city: str) -> tuple:
    """
    Bloqueia novas entradas PARA UMA CIDADE após sequência de perdas.
    """
    city_history = [t for t in history if (t.get("city", "") or "").strip().lower() == city.strip().lower()]
    consec = consecutive_losses(city_history)
    if consec < 3:
        return False, ""

    now = time.time()
    last_exit = 0.0
    for t in reversed(city_history):
        if t.get("result") != "OPEN":
            ts_str = t.get("exit_time") or t.get("entry_time") or ""
            try:
                from datetime import datetime, timezone
                dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                last_exit = dt.timestamp()
            except Exception:
                pass
            break

    cooldown_secs = {3: 2*3600, 4: 4*3600}.get(consec, 12*3600)
    if now - last_exit < cooldown_secs:
        hours_left = (cooldown_secs - (now - last_exit)) / 3600
        return True, f"cooldown cidade: {consec} perdas, aguarde {hours_left:.1f}h"
    return False, ""


def trading_cooldown(history: list) -> tuple:
    """
    Bloqueia novas entradas após sequência de perdas consecutivas.

    - 3 perdas seguidas → cooldown de 2 horas
    - 4 perdas seguidas → cooldown de 4 horas
    - 5+ perdas seguidas → cooldown de 12 horas
    - Um WIN quebra a sequência (zera o contador)
    - Um WIN recente (último trade) também bloqueia alerta

    Returns (bool blocked, str motivo).
    """
    consec = consecutive_losses(history)
    if consec < 3:
        return False, ""

    now = time.time()
    last_exit = 0.0
    for t in reversed(history):
        if t.get("result") != "OPEN":
            ts_str = t.get("exit_time") or t.get("entry_time") or ""
            try:
                from datetime import datetime, timezone
                dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                last_exit = dt.timestamp()
            except Exception:
                pass
            break

    if consec == 3:
        cooldown_secs = 2 * 3600
        label = "3"
    elif consec == 4:
        cooldown_secs = 4 * 3600
        label = "4"
    else:
        cooldown_secs = 12 * 3600
        label = f"{consec}"

    if now - last_exit < cooldown_secs:
        hours_left = (cooldown_secs - (now - last_exit)) / 3600
        return True, f"cooldown: {label} perdas consecutivas, aguarde {hours_left:.1f}h"

    return False, ""


# ── Circuit breaker de perda diária ─────────────────────────────

def risk_limits_ok(
    history: list,
    balance: float,
    start_balance: float,
) -> tuple:
    """
    Verifica se o risco global permite novas entradas.

    Regras:
    - Perda líquida diária (UTC) não pode exceder MAX_DAILY_LOSS.
    - Se saldo cair abaixo de start_balance, perda acumulada bloqueia.

    Returns (bool ok, str motivo).
    """
    from datetime import datetime, timezone
    from config import MAX_DAILY_LOSS

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    daily_loss = 0.0
    for t in history:
        if t.get("result") != "OPEN":
            ts = t.get("exit_time") or t.get("entry_time") or ""
            if today_str in ts:
                daily_loss += float(t.get("pnl", 0.0))

    if daily_loss < -MAX_DAILY_LOSS:
        return False, (
            f"diario: perda ${abs(daily_loss):.2f} excede limiar "
            f"${MAX_DAILY_LOSS:.2f}"
        )

    if balance < start_balance * 0.5:
        spread = start_balance - balance
        return False, f"drawdown: ${abs(spread):.2f} abaixo de 50% do bankroll"

    return True, "ok"


# ── Distância à borda mais próxima ───────────────────────────────

def _nearest_edge_distance(
    forecast_temp: float,
    condition: str,
    target_c: float,
    unit: str = "C",
    target_lo_raw: float = 0.0,
    target_hi_raw: float = 0.0,
) -> float:
    """
    Distância da previsão à borda mais próxima do bucket alvo.

    Todos os valores já chegam em °C (o caller converte antes de chamar).
    O parâmetro ``unit`` é informativo para compatibilidade com código
    que trabalha em °F — NÃO faz conversão aqui.

    Usado para filtrar trades onde o forecast está "no meio"
    do bucket (máxima incerteza).
    """
    forecast_c = forecast_temp
    if str(unit).upper() == "F":
        lo_c = (target_lo_raw - 32) * 5 / 9 if target_lo_raw is not None else None
        hi_c = (target_hi_raw - 32) * 5 / 9 if target_hi_raw is not None else None
    else:
        lo_c = target_lo_raw
        hi_c = target_hi_raw

    cond = condition.upper()

    if cond == "ABOVE":
        return max(0.0, forecast_c - target_c)

    if cond == "BELOW":
        return max(0.0, target_c - forecast_c)

    if cond == "EXACT":
        from model import delta_to_celsius
        half = delta_to_celsius(0.5, unit)
        lo_c = target_c - half
        hi_c = target_c + half
        if forecast_c < lo_c:
            return max(0.0, lo_c - forecast_c)
        if forecast_c > hi_c:
            return max(0.0, forecast_c - hi_c)
        return min(forecast_c - lo_c, hi_c - forecast_c)

    if cond == "RANGE2" and lo_c is not None and hi_c is not None:
        if lo_c > hi_c:
            lo_c, hi_c = hi_c, lo_c
        if forecast_c < lo_c:
            return max(0.0, lo_c - forecast_c)
        if forecast_c > hi_c:
            return max(0.0, forecast_c - hi_c)
        # Dentro do bucket → distância à borda mais próxima
        return min(forecast_c - lo_c, hi_c - forecast_c)

    # Fallback genérico
    return abs(forecast_c - target_c)



# ── Analytics Health Integration ───────────────────────────────

def apply_health_factor(stake: float, city: str = None):
    """
    Ajusta o stake usando o Analytics Health Engine (v5.8).
    Agora com boost para cidades lucrativas (Seoul, Tokyo, Madrid).
    """
    try:
        health = load_health()
        if not health:
            return stake, "health indisponível"

        if health.get("stop_trading", False):
            return 0.0, "Health: STOP TRADING"

        factor = float(health.get("kelly_factor", 1.0))

        # Boost v5.8: Se a cidade for top performer, ignoramos o fator redutor global
        if city and city.lower() in ["seoul", "tokyo", "madrid"]:
            factor = max(factor, 0.85) # Nunca menos de 85% para cidades elite
            logger.info(f"Boost aplicado para {city}: fator {factor:.2f}")

        factor = max(0.0, min(1.2, factor)) # Permitimos até 20% de alavancagem extra

        return round(stake * factor, 2), f"Kelly x {factor:.2f}"

    except Exception as exc:
        logger.exception("Erro carregando Health: %s", exc)
        return stake, "erro health"
