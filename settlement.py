"""
settlement.py — resolve trades abertos consultando a Gamma API da Polymarket.

FIX CRÍTICO: Após save_bankroll, recarrega do banco e verifica que os trades
realmente foram persistidos como WIN/LOSS. Se ainda aparecerem como OPEN,
força um segundo save para evitar o loop de notificações infinitas.

Estratégia de resolução em 3 camadas:
    1. Polymarket Gamma (yes_price >= 0.95 / <= 0.05)
    2. open-meteo ARCHIVE (dias passados)
    3. open-meteo FORECAST past_days=1 (dia atual, disponível ~6h UTC)
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

from config import (
    POLYMARKET_FEE,
    CITY_COORDS_BY_SLUG,
    CITY_SLUG_NORMALIZE,
    CITY_TIMEZONE,
)

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
    slug = CITY_SLUG_NORMALIZE.get(city_raw)
    if slug and slug in CITY_COORDS_BY_SLUG:
        return slug

    key = city_raw.lower().replace(" ", "-").replace("_", "-").strip()
    if key in CITY_COORDS_BY_SLUG:
        return key

    display_attempt = city_raw.replace("-", " ")
    slug2 = CITY_SLUG_NORMALIZE.get(display_attempt)
    if slug2 and slug2 in CITY_COORDS_BY_SLUG:
        return slug2

    city_lower = city_raw.lower().strip()
    for display, sl in CITY_SLUG_NORMALIZE.items():
        if display.lower() == city_lower or display.lower().replace(" ", "-") == city_lower:
            if sl in CITY_COORDS_BY_SLUG:
                return sl

    return None


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
            log_settlement(f"HTTP {r.status_code}: {url[:80]}")
        except Exception as e:
            log_settlement(f"Request erro (tentativa {attempt+1}): {e}")
        time.sleep(2 ** attempt)
    return None


# ── Estratégia 1: resolução via Polymarket Gamma API ─────────────────────────

def _resolve_via_polymarket(market_id):
    data = _safe_get(f"{GAMMA_BASE}/markets/{market_id}")
    if not data:
        return None, None

    closed         = data.get("closed", False)
    accepting      = data.get("acceptingOrders", True)
    uma_status     = data.get("umaResolutionStatus", "") or ""
    outcome_prices = data.get("outcomePrices")

    if closed is False and accepting is True and uma_status not in ("resolved", "proposed"):
        return "OPEN", None

    try:
        if isinstance(outcome_prices, str):
            prices = json.loads(outcome_prices)
        else:
            prices = list(outcome_prices) if outcome_prices else []
        yes_price = float(prices[0]) if prices else None
    except Exception:
        yes_price = None

    if yes_price is None:
        if uma_status in ("proposed",):
            log_settlement(f"  ⏳ UMA em disputa (proposed): market {market_id}")
            return "OPEN", None
        return None, None

    if yes_price >= 0.95:
        return "WIN", yes_price
    elif yes_price <= 0.05:
        return "LOSS", yes_price
    else:
        log_settlement(f"  ⏳ YES={yes_price:.3f} — aguardando resolução final: market {market_id}")
        return "OPEN", yes_price


# ── Estratégia 2: temperatura via open-meteo ARCHIVE ─────────────────────────

def _get_temp_archive(lat, lon, tz, date_str):
    url = (
        "https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={lat}&longitude={lon}"
        f"&start_date={date_str}&end_date={date_str}"
        f"&daily=temperature_2m_max&timezone={tz}"
    )
    try:
        r = requests.get(url, timeout=20)
        if r.status_code != 200:
            return None
        data = r.json()
        temps = data.get("daily", {}).get("temperature_2m_max", [])
        if temps and temps[0] is not None:
            return float(temps[0])
    except Exception as e:
        log_settlement(f"  [archive] erro: {e}")
    return None


# ── Estratégia 3: temperatura via open-meteo FORECAST (past_days) ────────────

def _get_temp_forecast_today(lat, lon, tz, date_str):
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&daily=temperature_2m_max&timezone={tz}"
        f"&forecast_days=1&past_days=2"
    )
    try:
        r = requests.get(url, timeout=20)
        if r.status_code != 200:
            return None
        data = r.json()
        dates = data.get("daily", {}).get("time", [])
        temps = data.get("daily", {}).get("temperature_2m_max", [])
        for d, t in zip(dates, temps):
            if d == date_str and t is not None:
                log_settlement(f"  [forecast/past] {date_str}: {t}°C ⚠️ dado de análise")
                return float(t)
    except Exception as e:
        log_settlement(f"  [forecast/past] erro: {e}")
    return None


def _get_real_temperature(city_raw, date_str):
    slug = _to_slug(city_raw)
    if not slug or slug not in CITY_COORDS_BY_SLUG:
        log_settlement(f"❌ Cidade desconhecida: '{city_raw}' (slug={slug})")
        return None

    lat, lon = CITY_COORDS_BY_SLUG[slug]
    tz = CITY_TIMEZONE.get(slug, "UTC")

    temp = _get_temp_archive(lat, lon, tz, date_str)
    if temp is not None:
        log_settlement(f"  [archive] {city_raw} {date_str}: {temp:.1f}°C ✅")
        return temp

    today_str     = utcnow().date().isoformat()
    yesterday_str = (utcnow().date() - timedelta(days=1)).isoformat()

    if date_str in (today_str, yesterday_str):
        log_settlement(f"  [archive] sem dados para {date_str} — tentando forecast/past...")
        temp2 = _get_temp_forecast_today(lat, lon, tz, date_str)
        if temp2 is not None:
            return temp2
        log_settlement(f"  ⚠️  Nenhuma fonte tem temperatura para {city_raw} {date_str} ainda")
    else:
        log_settlement(f"  ⚠️  Archive sem dados para {city_raw} {date_str}")

    return None


def _win_from_temp(real_temp_c, target_c, trade_type, trade):
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
        log_settlement(f"✅ WIN  | {city:15} | {market_date} | PnL: ${pnl:+.2f} | market {market_id}")
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
        log_settlement(f"❌ LOSS | {city:15} | {market_date} | PnL: -${stake:.2f} | market {market_id}")
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


# ── Verificação pós-save ──────────────────────────────────────────────────────

def _verificar_persistencia(ids_resolvidos):
    """
    Recarrega o bankroll do banco e verifica que os trades resolvidos
    nesta sessão realmente foram persistidos como WIN ou LOSS.
    Retorna lista de market_ids que ainda estão OPEN (falha de persistência).
    """
    try:
        bankroll_check = load_bankroll()
        ainda_open = []
        for t in bankroll_check.get("history", []):
            if t.get("market_id") in ids_resolvidos and t.get("result") == "OPEN":
                ainda_open.append(t.get("market_id"))
        return ainda_open
    except Exception as e:
        log_settlement(f"⚠️  Erro na verificação pós-save: {e}")
        return []


# ── Main ──────────────────────────────────────────────────────────────────────

def resolve_trades():
    log_settlement("=" * 50)
    log_settlement("🚀 INICIANDO SETTLEMENT")
    log_settlement(f"UTC NOW: {utcnow().isoformat()}")

    bankroll     = load_bankroll()
    history      = bankroll["history"]
    today        = utcnow().date()
    updated      = 0
    errors       = 0
    unresolvable = 0
    session      = {"wins": 0, "losses": 0, "pnl": 0.0}

    # IDs resolvidos nesta sessão — usados para verificação pós-save
    ids_resolvidos = []

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

        # Trades futuros são ignorados
        if trade_date > today:
            log_settlement(f"  ⏳ {city} {market_date}: futuro — aguardando")
            continue

        log_settlement(f"🔍 Checando: {city} {market_date} ({trade_type} {target}°{unit}) — market {market_id}")

        # Estratégia 1: Polymarket Gamma
        poly_result, yes_price = _resolve_via_polymarket(market_id)
        time.sleep(0.3)

        if poly_result in ("WIN", "LOSS"):
            win = (poly_result == "WIN")
            log_settlement(f"  → Polymarket: {'YES' if win else 'NO'} resolveu (YES price={yes_price:.3f})")
            _apply_result(bankroll, trade, win, None, session)
            ids_resolvidos.append(market_id)
            updated += 1
            continue

        # Estratégia 2 e 3: temperatura real
        log_settlement(f"  → Polymarket pendente — buscando temperatura real...")
        real_temp_c = _get_real_temperature(city, market_date)

        if real_temp_c is None:
            log_settlement(f"  ⚠️  Temperatura indisponível: {city} {market_date} — próximo ciclo")
            unresolvable += 1
            continue

        target_c = to_celsius(target, unit)
        win = _win_from_temp(real_temp_c, target_c, trade_type, trade)

        if win is None:
            log_settlement(f"  ⚠️  Tipo '{trade_type}' não suportado (ID={market_id})")
            errors += 1
            continue

        log_settlement(
            f"  → temp real: {real_temp_c:.1f}°C | target: {target_c:.1f}°C ({unit}) → {'WIN' if win else 'LOSS'}"
        )
        _apply_result(bankroll, trade, win, real_temp_c, session)
        ids_resolvidos.append(market_id)
        updated += 1

    # ── Salva e verifica persistência ────────────────────────────────────────
    if updated > 0:
        log_settlement(f"💾 Salvando {updated} trades resolvidos...")
        save_bankroll(bankroll)

        # Verifica se o banco realmente persistiu
        if ids_resolvidos:
            log_settlement("🔍 Verificando persistência no banco...")
            ainda_open = _verificar_persistencia(ids_resolvidos)
            if ainda_open:
                log_settlement(f"⚠️  ALERTA: {len(ainda_open)} trades ainda OPEN após save — forçando re-save")
                # Força segundo save com os mesmos dados em memória
                save_bankroll(bankroll)
                # Segunda verificação
                ainda_open2 = _verificar_persistencia(ids_resolvidos)
                if ainda_open2:
                    log_settlement(f"❌ CRÍTICO: Re-save também falhou para IDs: {ainda_open2}")
                    log_settlement("❌ Notificações foram enviadas mas banco não persistiu — INTERROMPENDO para evitar loop")
                    # Não envia resumo para evitar spam
                    return updated, errors, unresolvable
                else:
                    log_settlement("✅ Re-save bem-sucedido — persistência confirmada")
            else:
                log_settlement(f"✅ Persistência confirmada para {len(ids_resolvidos)} trade(s)")
    else:
        save_bankroll(bankroll)

    if VALIDACAO_OK and updated > 0:
        try:
            gerar_relatorio(enviar_telegram=True)
        except Exception as e:
            log_settlement(f"⚠️  validacao relatorio: {e}")

    wins      = sum(1 for t in history if t.get("result") == "WIN")
    losses    = sum(1 for t in history if t.get("result") == "LOSS")
    total_pnl = sum(t.get("pnl", 0) for t in history if t.get("result") in ("WIN", "LOSS"))

    log_settlement("")
    log_settlement("=" * 50)
    log_settlement("📊 SETTLEMENT SUMMARY")
    log_settlement("=" * 50)
    log_settlement(f"✅ Resolvidos agora:  {updated}")
    log_settlement(f"⚠️  Pendentes:         {unresolvable}")
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

    return updated, errors, unresolvable


if __name__ == "__main__":
    resolve_trades()
