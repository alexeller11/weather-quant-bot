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
"""

import os
import logging
from datetime import datetime, timedelta, timezone

# AUDITORIA bug #3: fonte única de sigma por horizonte. Antes havia
# três cópias inconsistentes {1:4,2:4.5,3:5} com defaults diferentes
# (5.0 aqui vs 6.0 em model.py e forecast.py) — modelo e gate de risco
# aplicavam sigma diferente ao mesmo mercado D+4+.
from model import get_base_sigma

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
    MAX_PRICE_RANGE2,
    MAX_PRICE,
    MAX_OPEN_TRADES,
    MAX_TOTAL_EXPOSURE,
    MAX_DAILY_TRADES,
    MAX_DAILY_LOSS,
    MAX_WEEKLY_LOSS,
    MAX_DRAWDOWN_PCT,
    MIN_PROB_RANGE2,
    MIN_EDGE_RANGE2,
    MIN_EDGE_NO,
    MAX_PROB_FOR_NO,
    FEE_RATE,
)


def _delta_to_celsius(delta: float, unit: str) -> float:
    """Converte largura/diferença de temperatura para °C."""
    if str(unit).upper() == "F":
        return delta * 5 / 9
    return delta

logger = logging.getLogger(__name__)

# Parâmetros para RANGE2 e NO importados de config.py (env-configurable).
# Ver config.py para valores-default e env vars.

# AJUSTE v5.5: 0.55 → 0.45
# Mercados EXACT atuais têm distribuição espalhada; nenhum bucket
# individual passa 0.55. Com 0.45 abrimos mercados válidos mantendo
# proteção contra YES já decidido.
MIN_PRICE_YES_FOR_NO = float(os.getenv("MIN_PRICE_YES_FOR_NO", "0.45"))

# FEE_RATE importado de config.py (env-configurable, shared com settlement.py).

# Limite de stake por EVENTO (cidade + data).
#
# AUDITORIA bug #8: por default MAX_EVENT_EXPOSURE == MAX_POSITION ($4).
# Isto significa que, no máximo, UMA aposta por evento chega a tamanho
# cheio — uma segunda aposta num bucket diferente do mesmo (city, date)
# fica capped a headroom ≈ $0. É intencional: o bot foi desenhado como
# "uma convicção por evento" para evitar que dois buckets contraditórios
# (ex.: ABOVE 25°C e RANGE2 24-26°C simultâneos) consumam o bankroll.
# Para permitir múltiplos buckets por evento, sobrescreva via env:
# MAX_EVENT_EXPOSURE=20 (igual ao MAX_TOTAL_EXPOSURE).
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


# ── Cooldown após sequência de losses ────────────────────────────────────
# Evita que o bot continue operando mecanicamente durante losing streaks.
# Settlement continua permitido para reduzir risco.

COOLDOWN_3LOSSES_H = float(os.getenv("COOLDOWN_3LOSSES_H", "4"))
COOLDOWN_5LOSSES_H = float(os.getenv("COOLDOWN_5LOSSES_H", "12"))


def trading_cooldown(history: list) -> tuple:
    """
    Verifica se o bot deve entrar em cooldown após consecutive losses.

    Retorna (ativo: bool, motivo: str).
    - 3 losses seguidos → cooldown de 4h
    - 5 losses seguidos → cooldown de 12h

    Settlement continua permitido (reduz exposição).
    """
    consec = consecutive_losses(history)
    if consec < 3:
        return False, ""

    # Determina duração do cooldown
    if consec >= 5:
        cooldown_hours = COOLDOWN_5LOSSES_H
        level = 5
    else:
        cooldown_hours = COOLDOWN_3LOSSES_H
        level = 3

    # Encontra a hora do último LOSS (mais recente)
    last_loss_time = None
    for t in reversed(history or []):
        if t.get("result") == "LOSS":
            raw = t.get("exit_time") or t.get("entry_time") or ""
            last_loss_time = _parse_dt(raw)
            break

    if last_loss_time is None:
        return False, ""

    now = datetime.now(timezone.utc)
    elapsed = (now - last_loss_time).total_seconds() / 3600

    if elapsed < cooldown_hours:
        remaining = cooldown_hours - elapsed
        return True, (
            f"cooldown ativo: {consec} losses seguidos (limite {level}), "
            f"faltam {remaining:.1f}h de {cooldown_hours:.0f}h"
        )

    return False, ""


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
    prob: float,
    price: float,
    balance: float = 100.0,
    fraction: float = None,
) -> float:
    if prob <= 0 or prob >= 1 or price <= 0 or price >= 1:
        return 0.0

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


def _nearest_edge_distance(
    forecast_temp: float,
    condition: str,
    target_c: float,
    unit: str,
    target_lo_raw=None,
    target_hi_raw=None,
) -> float:
    """
    Distância em °C do forecast à borda mais próxima do bucket.

    ABOVE/BELOW: borda = target_c (ponto singular).
    RANGE2:      borda = limite do bucket mais próximo do forecast.
    EXACT:       borda = (target ± 0.5 unidade) mais próxima do forecast.

    Retorna valor absoluto em °C.
    """
    condition = condition.upper()

    if condition in ("ABOVE", "BELOW"):
        return abs(forecast_temp - target_c)

    if condition == "RANGE2":
        lo_c = _to_celsius(target_lo_raw, unit) if target_lo_raw is not None else target_c - _delta_to_celsius(1.0, unit)
        hi_c = _to_celsius(target_hi_raw, unit) if target_hi_raw is not None else target_c + _delta_to_celsius(1.0, unit)
        if lo_c > hi_c:
            lo_c, hi_c = hi_c, lo_c
        dist_lo = abs(forecast_temp - lo_c)
        dist_hi = abs(forecast_temp - hi_c)
        return min(dist_lo, dist_hi)

    if condition == "EXACT":
        half = _delta_to_celsius(0.5, unit)
        low_edge = target_c - half
        high_edge = target_c + half
        dist_lo = abs(forecast_temp - low_edge)
        dist_hi = abs(forecast_temp - high_edge)
        return min(dist_lo, dist_hi)

    # fallback genérico
    return abs(forecast_temp - target_c)


def _to_celsius(value: float, unit: str) -> float:
    """Converte valor ABSOLUTO de temperatura para °C."""
    if str(unit).upper() == "F":
        return (value - 32) * 5 / 9
    return value


def check_guardrails(
    market: dict,
    model_prob: float,
    forecast_temp: float,
    sigma: float = None,
    side: str = "YES",
) -> bool:
    condition  = market.get("condition", "ABOVE").upper()
    target_raw = float(market.get("target_temp", 0))
    price_yes  = float(market.get("price", 0))
    day_offset = int(market.get("day_offset", 1))
    unit       = market.get("unit", "C").upper()
    target_lo  = market.get("target_lo")
    target_hi  = market.get("target_hi")

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
            target_lo=target_lo,
            target_hi=target_hi,
        )

    # === LÓGICA YES ===
    min_p = MIN_PRICE_RANGE2 if condition == "RANGE2" else MIN_PRICE
    if price_yes < min_p or price_yes > MAX_PRICE:
        logger.info(f"Bloqueado: preço fora da faixa ({price_yes:.3f}, min={min_p})")
        return False

    edge = model_prob - price_yes

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
        if price_yes > MAX_PRICE_RANGE2:
            logger.info(f"Bloqueado: RANGE2 preço alto demais ({price_yes:.3f} > {MAX_PRICE_RANGE2})")
            return False

    elif condition == "RANGE":
        logger.info("Bloqueado: tipo RANGE genérico não suportado")
        return False

    else:
        logger.info(f"Bloqueado: condition desconhecida ({condition})")
        return False

    # === ZSCORE CHECK (todas as condições com target) ===
    # Acima/below: distancia ao target; RANGE2/EXACT: distancia à borda mais próxima
    if forecast_temp is not None:
        if sigma is None or sigma <= 0:
            sigma = get_base_sigma(day_offset)

        sigma_cap = SIGMA_CAP_EXACT if condition == "EXACT" else SIGMA_CAP_ABOVE_BELOW
        sigma = min(sigma, sigma_cap)

        edge_dist = _nearest_edge_distance(
            forecast_temp, condition, target_c, unit,
            target_lo_raw=target_lo, target_hi_raw=target_hi,
        )
        z_score = edge_dist / sigma
        if z_score < MIN_TARGET_ZSCORE:
            logger.info(
                f"Bloqueado: zscore {z_score:.2f} < {MIN_TARGET_ZSCORE} "
                f"({condition} edge_dist={edge_dist:.1f}°C sigma={sigma:.2f})"
            )
            return False

    logger.info(
        f"GUARDRAIL OK [{side}]: {condition} target={target_raw}°{unit} "
        f"price_yes={price_yes:.3f} prob={model_prob:.3f} edge={edge:+.3f} EV={ev:+.3f}"
    )
    return True


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
) -> bool:
    """
    Guardrails para apostas NO.

    AJUSTE v5.5: RANGE2 agora suportado.
    A lógica é idêntica ao EXACT: apostamos que a temperatura NÃO cai
    no bucket. O zscore check verifica que o forecast está distante o
    suficiente da borda mais próxima do bucket para justificar a aposta.

    v5.6: zscore agora usa _nearest_edge_distance (borda mais próxima)
    em vez do midpoint, consistente com o lado YES.
    """
    if condition not in ("ABOVE", "BELOW", "EXACT", "RANGE2"):
        logger.info(f"NO nao suportado para {condition}")
        return False

    if price_yes < MIN_PRICE_YES_FOR_NO:
        logger.info(f"NO bloqueado: price_yes muito baixo ({price_yes:.3f} < {MIN_PRICE_YES_FOR_NO})")
        return False

    if model_prob > MAX_PROB_FOR_NO:
        logger.info(f"NO bloqueado: model_prob alta demais ({model_prob:.3f} > {MAX_PROB_FOR_NO})")
        return False

    no_edge = price_yes - model_prob
    if no_edge < MIN_EDGE_NO:
        logger.info(f"NO bloqueado: edge insuficiente ({no_edge:.3f} < {MIN_EDGE_NO})")
        return False

    price_no = 1.0 - price_yes
    if price_no < MIN_PRICE:
        logger.info(f"NO bloqueado: price_no muito baixo ({price_no:.3f})")
        return False

    ev_no = expected_value_no(model_prob, price_yes)
    if ev_no < MIN_EV:
        logger.info(
            f"NO bloqueado: EV líquido insuficiente ({ev_no:+.3f} < {MIN_EV})"
        )
        return False

    # Zscore check: exige que o forecast esteja suficientemente distante
    # da borda mais próxima do bucket/target.
    if forecast_temp is not None and target_c is not None:
        eff_sigma = sigma if (sigma and sigma > 0) else get_base_sigma(day_offset)
        sigma_cap = SIGMA_CAP_EXACT if condition == "EXACT" else SIGMA_CAP_ABOVE_BELOW
        eff_sigma = min(eff_sigma, sigma_cap)

        edge_dist = _nearest_edge_distance(
            forecast_temp, condition, target_c, unit,
            target_lo_raw=target_lo, target_hi_raw=target_hi,
        )
        z_score = edge_dist / eff_sigma
        if z_score < MIN_TARGET_ZSCORE:
            logger.info(
                f"NO bloqueado: zscore {z_score:.2f} < {MIN_TARGET_ZSCORE} "
                f"(forecast muito proximo da borda do bucket, dist={edge_dist:.1f}°C)"
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


def _parse_dt(raw: str):
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _closed_trades(history: list) -> list:
    return [t for t in history or [] if t.get("result") in ("WIN", "LOSS")]


def _pnl_since(history: list, start_dt: datetime) -> float:
    total = 0.0
    for trade in _closed_trades(history):
        exit_dt = _parse_dt(trade.get("exit_time") or "")
        if exit_dt is not None and exit_dt >= start_dt:
            total += float(trade.get("pnl") or 0)
    return round(total, 4)


def _trades_opened_since(history: list, start_dt: datetime) -> int:
    count = 0
    for trade in history or []:
        entry_dt = _parse_dt(trade.get("entry_time") or "")
        if entry_dt is not None and entry_dt >= start_dt:
            count += 1
    return count


def _max_drawdown_pct(history: list, start_balance: float) -> float:
    running = float(start_balance or 0)
    peak = running
    max_dd = 0.0
    for trade in sorted(_closed_trades(history), key=lambda t: t.get("exit_time") or ""):
        running += float(trade.get("pnl") or 0)
        peak = max(peak, running)
        if peak > 0:
            max_dd = max(max_dd, (peak - running) / peak * 100)
    return round(max_dd, 4)


def risk_limits_ok(history: list, balance: float, start_balance: float) -> tuple:
    """
    Circuit breaker de portfolio para novas entradas. Settlement continua
    permitido para reduzir risco e manter o estado sincronizado.
    """
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = day_start - timedelta(days=day_start.weekday())

    daily_count = _trades_opened_since(history, day_start)
    if daily_count >= MAX_DAILY_TRADES:
        return False, f"limite diario de trades atingido ({daily_count}/{MAX_DAILY_TRADES})"

    daily_pnl = _pnl_since(history, day_start)
    if daily_pnl <= -abs(MAX_DAILY_LOSS):
        return False, f"stop diario atingido (PnL ${daily_pnl:.2f})"

    weekly_pnl = _pnl_since(history, week_start)
    if weekly_pnl <= -abs(MAX_WEEKLY_LOSS):
        return False, f"stop semanal atingido (PnL ${weekly_pnl:.2f})"

    drawdown = _max_drawdown_pct(history, start_balance)
    if drawdown >= MAX_DRAWDOWN_PCT:
        return False, f"drawdown maximo atingido ({drawdown:.1f}% >= {MAX_DRAWDOWN_PCT:.1f}%)"

    if balance <= 0:
        return False, "saldo disponivel zerado"

    return True, "ok"
