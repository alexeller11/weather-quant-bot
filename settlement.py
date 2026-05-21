"""
settlement.py — resolve trades abertos consultando a Gamma API da Polymarket.

Estratégia:
  1. Para cada trade OPEN, busca GET /markets/{id} na Gamma API.
  2. Se o mercado está fechado (closed=True ou acceptingOrders=False)
     e outcomePrices resolveu (YES≈1 ou YES≈0), determina WIN/LOSS.
  3. Fallback: se o mercado ainda não resolveu na Polymarket mas a data
     já passou, tenta a temperatura real via open-meteo archive.
"""

import requests
import json
import time
from datetime import datetime, timezone, timedelta

def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)

from bankroll import load_bankroll, save_bankroll
try:
    from validacao import registrar_resultado, gerar_relatorio
    VALIDACAO_OK = True
except Exception:
    VALIDACAO_OK = False

from config import POLYMARKET_FEE, CITY_COORDS_BY_SLUG, CITY_SLUG_NORMALIZE

try:
    from notificador import (
        notificar_settlement_win,
        notificar_settlement_loss,
        notificar_settlement_resumo,
    )
    TELEGRAM_OK = True
except Exception as e:
    print(f"⚠️  Telegram indisponível: {e}")
    TELEGRAM_OK = False
    def notificar_settlement_win(*a, **kw): pass
    def notificar_settlement_loss(*a, **kw): pass
    def notificar_settlement_resumo(*a, **kw): pass

GAMMA_BASE = "https://gamma-api.polymarket.com"
HEADERS    = {"User-Agent": "Mozilla/5.0"}
LOG_FILE   = "settlement.log"

# ── Helpers ──────────────────────────────────────────────────────────────────

def log_settlement(msg):
    ts   = utcnow().isoformat()
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _to_slug(city_raw):
    key  = city_raw.lower().replace(" ", "-").replace("_", "-").strip()
    if key in CITY_COORDS_BY_SLUG:
        return key
    key2 = city_raw.lower().replace("-", " ").strip()
    return CITY_SLUG_NORMALIZE.get(key) or CITY_SLUG_NORMALIZE.get(key2)


def to_celsius(value, unit):
    if unit and str(unit).upper() == "F":
        return (float(value) - 32.0) * 5.0 / 9.0
    return float(value)


def _safe_get(url, retries=3):
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                log_settlement("Rate limit (429). Aguardando 60s...")
                time.sleep(60)
                continue
            log_settlement(f"HTTP {r.status_code}: {url}")
        except Exception as e:
            log_settlement(f"Request erro (tentativa {attempt+1}): {e}")
        time.sleep(2 ** attempt)
    return None


# ── Estratégia 1: resolução via Polymarket Gamma API ─────────────────────────

def _resolve_via_polymarket(market_id):
    """
    Consulta GET /markets/{id} e determina resultado.

    Retorna:
        "WIN"   — YES resolveu em ~1.0
        "LOSS"  — YES resolveu em ~0.0
        "OPEN"  — mercado ainda não resolveu
        None    — erro ou dados insuficientes
    """
    data = _safe_get(f"{GAMMA_BASE}/markets/{market_id}")
    if not data:
        return None, None

    closed          = data.get("closed", False)
    accepting       = data.get("acceptingOrders", True)
    uma_status      = data.get("umaResolutionStatus", "") or ""
    outcome_prices  = data.get("outcomePrices")

    # Mercado ainda ativo — não resolveu
    if closed is False and accepting is True and uma_status not in ("resolved", "proposed"):
        return "OPEN", None

    # Tenta ler preço do YES
    try:
        if isinstance(outcome_prices, str):
            prices = json.loads(outcome_prices)
        else:
            prices = list(outcome_prices) if outcome_prices else []

        yes_price = float(prices[0]) if prices else None
    except Exception:
        yes_price = None

    if yes_price is None:
        # closed mas sem preço ainda (UMA em disputa) — aguarda
        if uma_status in ("proposed",):
            log_settlement(f"  ⏳ UMA em disputa (proposed): market {market_id}")
            return "OPEN", None
        return None, None

    # YES ≥ 0.95 → WIN; YES ≤ 0.05 → LOSS; fora disso ainda pendente
    if yes_price >= 0.95:
        return "WIN", yes_price
    elif yes_price <= 0.05:
        return "LOSS", yes_price
    else:
        # Preço intermediário — resolução ainda pendente
        log_settlement(f"  ⏳ YES={yes_price:.3f} — aguardando resolução final: market {market_id}")
        return "OPEN", yes_price


# ── Estratégia 2: fallback temperatura open-meteo (D+1 ou posterior) ─────────

def _get_real_temperature(city_raw, date):
    slug = _to_slug(city_raw)
    if not slug or slug not in CITY_COORDS_BY_SLUG:
        log_settlement(f"❌ Cidade desconhecida: '{city_raw}'")
        return None
    lat, lon = CITY_COORDS_BY_SLUG[slug]
    url = (
        "https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={lat}&longitude={lon}"
        f"&start_date={date}&end_date={date}"
        "&daily=temperature_2m_max&timezone=UTC"
    )
    try:
        r    = requests.get(url, timeout=20)
        data = r.json()
        if "daily" not in data:
            return None
        temps = data["daily"].get("temperature_2m_max", [])
        if not temps or temps[0] is None:
            return None
        return float(temps[0])
    except requests.Timeout:
        log_settlement(f"⏱️  Timeout open-meteo ({city_raw} {date})")
        return None
    except Exception as e:
        log_settlement(f"❌ Erro open-meteo ({city_raw} {date}): {e}")
        return None


def _win_from_temp(real_temp_c, target_c, trade_type, trade):
    """Determina WIN/LOSS pela temperatura real."""
    if trade_type == "ABOVE":
        return real_temp_c >= target_c
    elif trade_type == "BELOW":
        return real_temp_c <= target_c
    elif trade_type == "EXACT":
        return abs(real_temp_c - target_c) <= 0.5
    elif trade_type == "RANGE":
        target_high = trade.get("target_high")
        if target_high is None:
            return None
        target_high_c = to_celsius(target_high, trade.get("unit", "C"))
        return target_c <= real_temp_c <= target_high_c
    return None


# ── Aplicar resultado ─────────────────────────────────────────────────────────

def _apply_result(bankroll, trade, win, real_temp_c, session):
    stake        = float(trade.get("stake", 0))
    market_price = float(trade.get("market_price", 0))
    city         = trade.get("city", "")
    market_date  = trade.get("market_date", "")
    target       = trade.get("target")
    unit         = trade.get("unit", "C")
    market_id    = trade.get("market_id", "?")

    if real_temp_c is not None:
        trade["real_temp_c"] = round(real_temp_c, 2)

    if win:
        gross_payout = stake / market_price
        fee          = (gross_payout - stake) * POLYMARKET_FEE
        payout       = gross_payout - fee
        pnl          = payout - stake
        bankroll["balance"] += payout
        trade["result"] = "WIN"
        trade["pnl"]    = round(pnl, 2)
        trade["fee"]    = round(fee, 2)
        session["wins"]  += 1
        session["pnl"]   += pnl
        log_settlement(
            f"✅ WIN | {city:15} | {market_date} | "
            f"PnL: ${pnl:+.2f} | market {market_id}"
        )
        try:
            notificar_settlement_win(
                city=city, market_date=market_date, target=target, unit=unit,
                stake=stake, pnl=round(pnl, 2),
                saldo=round(bankroll["balance"], 2),
                model_prob=trade.get("model_prob"),
                real_temp_c=real_temp_c,
            )
        except Exception as e:
            log_settlement(f"⚠️  Telegram WIN: {e}")
        if VALIDACAO_OK:
            try:
                registrar_resultado(market_id, "WIN", real_temp_c, round(pnl, 2))
            except Exception as e:
                log_settlement(f"⚠️  validacao WIN: {e}")
    else:
        trade["result"] = "LOSS"
        trade["pnl"]    = round(-stake, 2)
        trade["fee"]    = 0.0
        session["losses"] += 1
        session["pnl"]    -= stake
        log_settlement(
            f"❌ LOSS | {city:15} | {market_date} | "
            f"PnL: -${stake:.2f} | market {market_id}"
        )
        try:
            notificar_settlement_loss(
                city=city, market_date=market_date, target=target, unit=unit,
                stake=stake, pnl=round(-stake, 2),
                saldo=round(bankroll["balance"], 2),
                model_prob=trade.get("model_prob"),
                real_temp_c=real_temp_c,
            )
        except Exception as e:
            log_settlement(f"⚠️  Telegram LOSS: {e}")
        if VALIDACAO_OK:
            try:
                registrar_resultado(market_id, "LOSS", real_temp_c, round(-stake, 2))
            except Exception as e:
                log_settlement(f"⚠️  validacao LOSS: {e}")

    trade["exit_time"] = utcnow().isoformat()


# ── Main ──────────────────────────────────────────────────────────────────────

def resolve_trades():
    log_settlement("=" * 50)
    log_settlement("🚀 INICIANDO SETTLEMENT")
    log_settlement(f"UTC NOW: {utcnow().isoformat()}")

    bankroll    = load_bankroll()
    history     = bankroll["history"]
    today       = utcnow().date()
    updated     = 0
    errors      = 0
    session     = {"wins": 0, "losses": 0, "pnl": 0.0}

    open_trades = [t for t in history if t.get("result") == "OPEN"]
    log_settlement(f"Total trades OPEN: {len(open_trades)}")

    for trade in open_trades:
        market_id   = trade.get("market_id", "?")
        city        = trade.get("city", "")
        target      = trade.get("target")
        market_date = trade.get("market_date", "")
        trade_type  = trade.get("type", "ABOVE").upper()
        unit        = trade.get("unit", "C")

        if not city or not market_date or target is None:
            log_settlement(f"⚠️  Trade incompleto (ID={market_id})")
            errors += 1
            continue

        try:
            trade_date = datetime.strptime(market_date, "%Y-%m-%d").date()
        except Exception as e:
            log_settlement(f"⚠️  Data inválida '{market_date}': {e}")
            errors += 1
            continue

        log_settlement(f"🔍 Checando: {city} {market_date} ({trade_type} {target}°{unit}) — market {market_id}")

        # ── Estratégia 1: Polymarket Gamma ───────────────────────────────────
        poly_result, yes_price = _resolve_via_polymarket(market_id)
        time.sleep(0.3)  # gentileza com a API

        if poly_result in ("WIN", "LOSS"):
            win = (poly_result == "WIN")
            log_settlement(
                f"  → Polymarket: {'YES' if win else 'NO'} resolveu "
                f"(YES price={yes_price:.3f})"
            )
            _apply_result(bankroll, trade, win, None, session)
            updated += 1
            continue

        if poly_result == "OPEN":
            # Mercado ainda ativo na Polymarket
            if trade_date >= today:
                log_settlement(f"  ⏳ Mercado ainda aberto na Polymarket — aguardando")
                continue
            # Data passou mas Polymarket ainda não resolveu — tenta open-meteo
            log_settlement(f"  ⚠️  Data vencida mas Polymarket pendente — tentando open-meteo")

        # ── Estratégia 2: open-meteo archive (fallback) ──────────────────────
        if trade_date >= today:
            # Hoje ou futuro — open-meteo não tem dados ainda
            log_settlement(f"  ⏳ {city} {market_date}: aguardando (data ainda não passou)")
            continue

        real_temp_c = _get_real_temperature(city, market_date)
        if real_temp_c is None:
            log_settlement(f"  ⚠️  Temperatura indisponível via open-meteo: {city} {market_date}")
            errors += 1
            continue

        target_c = to_celsius(target, unit)
        win = _win_from_temp(real_temp_c, target_c, trade_type, trade)

        if win is None:
            log_settlement(f"  ⚠️  Tipo '{trade_type}' não suportado (ID={market_id})")
            errors += 1
            continue

        log_settlement(
            f"  → open-meteo: real={real_temp_c:.1f}°C target={target_c:.1f}°C ({unit}) → {'WIN' if win else 'LOSS'}"
        )
        _apply_result(bankroll, trade, win, real_temp_c, session)
        updated += 1

    save_bankroll(bankroll)

    # Relatório de validação
    if VALIDACAO_OK and updated > 0:
        try:
            gerar_relatorio(enviar_telegram=True)
        except Exception as e:
            log_settlement(f"⚠️  validacao relatorio: {e}")

    # Resumo
    wins      = sum(1 for t in history if t.get("result") == "WIN")
    losses    = sum(1 for t in history if t.get("result") == "LOSS")
    total_pnl = sum(t.get("pnl", 0) for t in history if t.get("result") in ("WIN", "LOSS"))

    log_settlement("")
    log_settlement("=" * 50)
    log_settlement("📊 SETTLEMENT SUMMARY")
    log_settlement("=" * 50)
    log_settlement(f"✅ Resolvidos agora:  {updated}")
    log_settlement(f"❌ Erros:             {errors}")
    log_settlement(f"📈 Total WIN/LOSS:    {wins}W / {losses}L")
    if (wins + losses) > 0:
        log_settlement(f"📊 Win rate:          {wins/(wins+losses)*100:.1f}%")
    log_settlement(f"💰 PnL total:         ${total_pnl:+.2f}")
    log_settlement(f"💵 Saldo atual:       ${bankroll['balance']:.2f}")
    log_settlement("=" * 50)

    if updated > 0:
        try:
            notificar_settlement_resumo(
                total_resolved=updated,
                wins=session["wins"],
                losses=session["losses"],
                total_pnl=round(session["pnl"], 2),
                saldo=round(bankroll["balance"], 2),
            )
        except Exception as e:
            log_settlement(f"⚠️  Telegram resumo: {e}")

    return updated, errors


if __name__ == "__main__":
    resolve_trades()
