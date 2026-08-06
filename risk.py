#!/usr/bin/env python3
"""
risk.py — Kelly Criterion e guardrails

TODOS os parâmetros vêm de config.py. Este módulo redefinia localmente
MIN_PROB_RANGE2, MIN_EDGE_RANGE2, MIN_EDGE_NO, MAX_PROB_FOR_NO, FEE_RATE,
MIN_PRICE_YES_FOR_NO e MAX_EVENT_EXPOSURE com valores hardcoded, o que
fazia qualquer override por variável de ambiente ser silenciosamente
ignorado. Os re-exports abaixo existem só para não quebrar imports
antigos (`from risk import MIN_EDGE_NO`).
"""

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
    # antes hardcoded aqui:
    MIN_PROB_RANGE2,
    MIN_EDGE_RANGE2,
    MIN_EDGE_NO,
    MAX_PROB_FOR_NO,
    MAX_PRICE_RANGE2,
    MAX_EDGE_RANGE2,
    MIN_PRICE_YES_FOR_NO,
    MAX_EVENT_EXPOSURE,
    MAX_BUCKET_ZDIST,
    FEE_RATE,
)

from analytics.storage import load_health

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
    if model_prob <= 0 or model_prob >= 1 or price <= 0 or price >= 1:
        return 0.0

    b = _net_odds(price)
    if b <= 0:
        return 0.0
    q = 1.0 - model_prob

    kelly_pct = (model_prob * b - q) / b
    kelly_pct = max(0.0, kelly_pct)

    frac = fraction if fraction is not None else KELLY_FRACTION

    # Ajuste por Health Factor (Score de performance)
    stake_adj, reason = apply_health_factor(1.0)
    frac = frac * stake_adj
    if stake_adj != 1.0:
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


def _bucket_bounds_c(condition: str, target_c: float, unit: str,
                     target_lo_raw=None, target_hi_raw=None):
    """Limites do bucket em °C. Retorna (lo_c, hi_c)."""
    from model import delta_to_celsius, to_celsius

    cond = str(condition).upper()
    if cond == "RANGE2" and target_lo_raw is not None and target_hi_raw is not None:
        lo_c = to_celsius(float(target_lo_raw), unit)
        hi_c = to_celsius(float(target_hi_raw), unit)
    else:
        half = delta_to_celsius(0.5 if cond == "EXACT" else 1.0, unit)
        lo_c, hi_c = target_c - half, target_c + half
    if lo_c > hi_c:
        lo_c, hi_c = hi_c, lo_c
    return lo_c, hi_c


def _bucket_distance(forecast_c: float, condition: str, target_c: float,
                     unit: str = "C", target_lo_raw=None, target_hi_raw=None):
    """
    Retorna (dentro_do_bucket, distancia_em_C_a_borda_mais_proxima).

    Quando a previsão está dentro do bucket, a distância é a menor das
    duas bordas (útil para medir "no meio do bucket"). Quando está fora, é
    a distância até a borda mais próxima.
    """
    lo_c, hi_c = _bucket_bounds_c(condition, target_c, unit, target_lo_raw, target_hi_raw)
    if forecast_c < lo_c:
        return False, lo_c - forecast_c
    if forecast_c > hi_c:
        return False, forecast_c - hi_c
    return True, min(forecast_c - lo_c, hi_c - forecast_c)


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
            unit=unit,
            target_lo=market.get("target_lo"),
            target_hi=market.get("target_hi"),
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

    elif condition in ("EXACT", "RANGE2"):
        min_edge = MIN_EDGE_EXACT if condition == "EXACT" else MIN_EDGE_RANGE2

        if model_prob < MIN_PROB_RANGE2:
            return False, "prob_baixa"
        if edge < min_edge:
            return False, "edge_insuficiente"
        # MAX_EDGE_RANGE2 estava definido só em comentário: um edge grande
        # num bucket estreito é sinal de erro de modelo ou de dado, não de
        # oportunidade.
        if edge > MAX_EDGE_RANGE2:
            return False, "edge_alto_demais"
        if price_yes > MAX_PRICE_RANGE2:
            return False, "preco_alto"

        # Sanidade física: comprar YES num bucket exige que a previsão
        # esteja DENTRO ou perto dele. Sem este gate, o bot comprou 22
        # buckets de 74-85°F em Los Angeles com previsão de 90-100°F —
        # 0 acertos. É a proteção que não depende de o modelo estar certo.
        if sigma is None or sigma <= 0:
            sigma = {1: 4.0, 2: 4.5, 3: 5.0}.get(day_offset, 5.0)
        sigma = min(sigma, SIGMA_CAP_EXACT)
        inside, edge_dist = _bucket_distance(
            forecast_temp, condition, target_c, unit,
            market.get("target_lo"), market.get("target_hi"),
        )
        if not inside and (edge_dist / sigma) > MAX_BUCKET_ZDIST:
            return False, "forecast_fora_do_bucket"

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
    unit: str = "C",
    target_lo=None,
    target_hi=None,
) -> tuple:
    """
    Guardrails para apostas NO.
    Retorna (bool ok, str reason).
    """
    condition = str(condition).upper()
    if condition not in ("ABOVE", "BELOW", "EXACT", "RANGE2"):
        return False, "condicao_nao_suportada"

    if price_yes < MIN_PRICE_YES_FOR_NO:
        return False, "price_yes_baixo"

    if model_prob > MAX_PROB_FOR_NO:
        return False, "prob_alta"

    no_edge = price_yes - model_prob
    if no_edge < MIN_EDGE_NO:
        return False, "edge_insuficiente"

    # Teto de edge — o lado YES ja tinha isso (MAX_EDGE_RANGE2 /
    # _max_edge_for_prob), o NO nao. Edge grande demais e' sinal de erro
    # de modelo/dado, nao de oportunidade, nos dois lados. Sem este teto,
    # o trade de Chicago de 2026-08-01 passou com +42% de edge sem
    # nenhuma checagem (fisicamente coerente naquele caso, mas a proteção
    # não pode depender de sorte).
    max_no_edge = MAX_EDGE_RANGE2 if condition in ("EXACT", "RANGE2") else _max_edge_for_prob(1.0 - model_prob)
    if no_edge > max_no_edge:
        return False, "edge_alto_demais"

    price_no = 1.0 - price_yes
    if price_no < MIN_PRICE:
        return False, "price_no_baixo"

    ev_no = expected_value_no(model_prob, price_yes)
    if ev_no < MIN_EV:
        return False, "ev_insuficiente"

    # Zscore check — a distância relevante é até a BORDA do bucket, não
    # até o centro. Para EXACT/RANGE2 o centro fica 0.28°C a 0.56°C dentro
    # do bucket, então medir do centro superestimava a distância e deixava
    # passar NO com a previsão dentro do bucket (onde NO tende a perder).
    if forecast_temp is not None and target_c is not None:
        eff_sigma = sigma if (sigma and sigma > 0) else {1: 4.0, 2: 4.5, 3: 5.0}.get(day_offset, 5.0)
        if condition in ("EXACT", "RANGE2"):
            eff_sigma = min(eff_sigma, SIGMA_CAP_EXACT)
            inside, dist = _bucket_distance(
                forecast_temp, condition, target_c, unit, target_lo, target_hi
            )
            if inside:
                return False, "forecast_dentro_do_bucket"
        else:
            eff_sigma = min(eff_sigma, SIGMA_CAP_ABOVE_BELOW)
            dist = abs(forecast_temp - target_c)
        if (dist / eff_sigma) < MIN_TARGET_ZSCORE:
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
    stake_adj, reason = apply_health_factor(1.0)
    frac = frac * stake_adj
    if stake_adj != 1.0:
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
    Ajusta o stake usando o Analytics Health Engine.

    O parâmetro `city` é aceito por compatibilidade e IGNORADO. Existia um
    boost que forçava factor >= 0.85 para Seoul, Tokyo e Madrid, ou seja,
    desarmava o freio global exatamente nas três cidades escolhidas por
    terem ganhado — com n=7, n=8 e n=9 trades. Isso é seleção pelo
    resultado passado, sem teste de significância, e foi removido.

    O factor também é limitado a 1.0: o cap anterior de 1.2 ("20% de
    alavancagem extra") aumenta a probabilidade de ruína sem aumentar o
    retorno esperado de longo prazo — Kelly acima de 1x é dominado.
    """
    try:
        health = load_health()
        if not health:
            return stake, "health indisponível"

        if health.get("stop_trading", False):
            return 0.0, "Health: STOP TRADING"

        factor = float(health.get("kelly_factor", 1.0))
        factor = max(0.0, min(1.0, factor))

        return round(stake * factor, 4), f"Kelly x {factor:.2f}"

    except Exception as exc:
        logger.exception("Erro carregando Health: %s", exc)
        return stake, "erro health"
