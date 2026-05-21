import requests
import json
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

# FIX: import do notificador correto (não telegram.py, evita colisão de nome)
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

# ==========================================
# LOG ESTRUTURADO
# ==========================================

LOG_FILE = "settlement.log"

def log_settlement(msg):
    """Escreve log com timestamp."""
    ts   = utcnow().isoformat()
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

# ==========================================
# NORMALIZE CITY → SLUG
# ==========================================

def _to_slug(city_raw):
    """
    Converte qualquer variação de nome de cidade para o slug canônico
    usado em CITY_COORDS_BY_SLUG (ex: 'Los Angeles' → 'los-angeles').
    """
    key = city_raw.lower().replace(" ", "-").replace("_", "-").strip()
    if key in CITY_COORDS_BY_SLUG:
        return key
    key2 = city_raw.lower().replace("-", " ").strip()
    slug = CITY_SLUG_NORMALIZE.get(key) or CITY_SLUG_NORMALIZE.get(key2)
    return slug

# ==========================================
# TEMPERATURA REAL (open-meteo archive)
# ==========================================

def get_real_temperature(city_raw, date):
    """
    Retorna temperatura máxima real (°C) do dia via open-meteo archive.

    timezone=UTC fixo para consistência — com timezone=auto, cidades em
    UTC+9 (Seoul, Tokyo) já estão no dia seguinte quando settlement roda
    de madrugada UTC, devolvendo a temperatura do dia errado.
    """
    slug = _to_slug(city_raw)

    if not slug or slug not in CITY_COORDS_BY_SLUG:
        log_settlement(f"❌ Cidade desconhecida: '{city_raw}'")
        return None

    lat, lon = CITY_COORDS_BY_SLUG[slug]

    url = (
        "https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={lat}"
        f"&longitude={lon}"
        f"&start_date={date}"
        f"&end_date={date}"
        "&daily=temperature_2m_max"
        "&timezone=UTC"
    )

    try:
        r    = requests.get(url, timeout=20)
        data = r.json()

        if "daily" not in data:
            log_settlement(f"❌ Sem dados para {city_raw} em {date}")
            return None

        temps = data["daily"].get("temperature_2m_max", [])
        if not temps or temps[0] is None:
            log_settlement(f"❌ Temperatura NULL para {city_raw} em {date}")
            return None

        return float(temps[0])

    except requests.Timeout:
        log_settlement(f"⏱️ TIMEOUT weather API ({city_raw} {date})")
        return None
    except Exception as e:
        log_settlement(f"❌ Erro weather API ({city_raw} {date}): {e}")
        return None

# ==========================================
# CONVERSÃO F → C
# ==========================================

def to_celsius(value, unit):
    if unit and str(unit).upper() == "F":
        return (float(value) - 32.0) * 5.0 / 9.0
    return float(value)

# ==========================================
# SETTLEMENT
# ==========================================

def resolve_trades():
    log_settlement("=" * 50)
    log_settlement("🚀 INICIANDO SETTLEMENT")
    log_settlement(f"UTC NOW: {utcnow().isoformat()}")

    bankroll = load_bankroll()
    history  = bankroll["history"]
    today    = utcnow().date()
    updated  = 0
    errors   = 0

    # Contadores para notificação de resumo
    session_wins   = 0
    session_losses = 0
    session_pnl    = 0.0

    # FILTER: trades OPEN que estão vencidos (date <= today)
    open_trades = [t for t in history if t.get("result") == "OPEN"]
    log_settlement(f"Total trades OPEN: {len(open_trades)}")

    for trade in open_trades:
        try:
            market_id   = trade.get("market_id", "?")
            city        = trade.get("city", "")
            target      = trade.get("target")
            market_date = trade.get("market_date")
            trade_type  = trade.get("type", "ABOVE")
            unit        = trade.get("unit", "C")

            if not city or not market_date or target is None:
                log_settlement(f"⚠️  Trade incompleto (ID={market_id}): {trade}")
                errors += 1
                continue

            trade_date = datetime.strptime(market_date, "%Y-%m-%d").date()

            if trade_date > today:
                log_settlement(f"⏳ {city} {market_date}: futuro, ainda não resolve")
                continue

            log_settlement(
                f"🔍 Resolvendo: {city} {market_date} ({trade_type} {target}°{unit})"
            )

            real_temp_c = get_real_temperature(city, market_date)

            if real_temp_c is None:
                log_settlement(f"⚠️  Temperatura indisponível: {city} {market_date}")
                errors += 1
                continue

            trade["real_temp_c"] = round(real_temp_c, 2)
            target_c = to_celsius(target, unit)

            stake        = float(trade.get("stake", 0))
            market_price = float(trade.get("market_price", 0))

            if market_price <= 0 or stake <= 0:
                log_settlement(
                    f"⚠️  Valores inválidos: stake={stake}, price={market_price}"
                )
                errors += 1
                continue

            if trade_type == "ABOVE":
                win = real_temp_c >= target_c
            elif trade_type == "BELOW":
                win = real_temp_c <= target_c
            elif trade_type == "EXACT":
                win = abs(real_temp_c - target_c) <= 0.5
            elif trade_type == "RANGE":
                target_high = trade.get("target_high")
                if target_high is None:
                    log_settlement(f"⚠️  RANGE sem target_high (ID={market_id})")
                    errors += 1
                    continue
                target_high_c = to_celsius(target_high, unit)
                win = target_c <= real_temp_c <= target_high_c
            else:
                log_settlement(f"⚠️  Tipo '{trade_type}' não suportado (ID={market_id})")
                errors += 1
                continue

            current_balance = bankroll["balance"]

            if win:
                gross_payout = stake / market_price
                fee          = (gross_payout - stake) * POLYMARKET_FEE
                payout       = gross_payout - fee
                pnl          = payout - stake
                bankroll["balance"] += payout
                trade["result"] = "WIN"
                trade["pnl"]    = round(pnl, 2)
                trade["fee"]    = round(fee, 2)
                result_str = "✅ WIN"
                session_wins  += 1
                session_pnl   += pnl

                # FIX: notificação Telegram de WIN (não existia antes)
                try:
                    notificar_settlement_win(
                        city=city,
                        market_date=market_date,
                        target=target,
                        unit=unit,
                        stake=stake,
                        pnl=round(pnl, 2),
                        saldo=round(bankroll["balance"], 2),
                        model_prob=trade.get("model_prob"),
                        real_temp_c=real_temp_c,
                    )
                except Exception as e:
                    log_settlement(f"⚠️  Telegram WIN: {e}")

                # Registrar resultado na validação
                if VALIDACAO_OK:
                    try:
                        registrar_resultado(market_id, "WIN", real_temp_c, round(pnl, 2))
                    except Exception as e:
                        log_settlement(f"⚠️  validacao WIN: {e}")

            else:
                trade["result"] = "LOSS"
                trade["pnl"]    = round(-stake, 2)
                trade["fee"]    = 0.0
                result_str = "❌ LOSS"
                session_losses += 1
                session_pnl    -= stake

                # FIX: notificação Telegram de LOSS (não existia antes)
                try:
                    notificar_settlement_loss(
                        city=city,
                        market_date=market_date,
                        target=target,
                        unit=unit,
                        stake=stake,
                        pnl=round(-stake, 2),
                        saldo=round(bankroll["balance"], 2),
                        model_prob=trade.get("model_prob"),
                        real_temp_c=real_temp_c,
                    )
                except Exception as e:
                    log_settlement(f"⚠️  Telegram LOSS: {e}")

                # Registrar resultado na validação
                if VALIDACAO_OK:
                    try:
                        registrar_resultado(market_id, "LOSS", real_temp_c, round(-stake, 2))
                    except Exception as e:
                        log_settlement(f"⚠️  validacao LOSS: {e}")

            trade["exit_time"] = utcnow().isoformat()
            updated += 1

            log_settlement(
                f"{result_str} | {city:15} | {market_date} | "
                f"Real: {real_temp_c:6.1f}°C | "
                f"Target: {target_c:6.1f}°C ({unit}) | "
                f"PnL: ${trade['pnl']:+8.2f}"
            )

        except Exception as e:
            log_settlement(f"❌ ERRO em trade {market_id}: {e}")
            errors += 1
            import traceback
            log_settlement(traceback.format_exc())

    save_bankroll(bankroll)

    # Gerar relatório de validação após cada settlement
    if VALIDACAO_OK and updated > 0:
        try:
            gerar_relatorio(enviar_telegram=True)
        except Exception as e:
            log_settlement(f"⚠️  validacao relatorio: {e}")

    # ── RESUMO ───────────────────────────────────────────────────────────────
    wins      = sum(1 for t in history if t.get("result") == "WIN")
    losses    = sum(1 for t in history if t.get("result") == "LOSS")
    total_pnl = sum(
        t.get("pnl", 0) for t in history
        if t.get("result") in ("WIN", "LOSS")
    )

    log_settlement("")
    log_settlement("=" * 50)
    log_settlement("📊 SETTLEMENT SUMMARY")
    log_settlement("=" * 50)
    log_settlement(f"✅ Resolvidos agora:  {updated}")
    log_settlement(f"❌ Erros:             {errors}")
    log_settlement(f"📈 Total WIN/LOSS:    {wins}W / {losses}L")
    if (wins + losses) > 0:
        wr = wins / (wins + losses) * 100
        log_settlement(f"📊 Win rate:          {wr:.1f}%")
    log_settlement(f"💰 PnL total:         ${total_pnl:+.2f}")
    log_settlement(f"💵 Saldo atual:       ${bankroll['balance']:.2f}")
    log_settlement("=" * 50)
    log_settlement("")

    # FIX: notificação Telegram de resumo (só se resolveu algo)
    if updated > 0:
        try:
            notificar_settlement_resumo(
                total_resolved=updated,
                wins=session_wins,
                losses=session_losses,
                total_pnl=round(session_pnl, 2),
                saldo=round(bankroll["balance"], 2),
            )
        except Exception as e:
            log_settlement(f"⚠️  Telegram resumo: {e}")

    return updated, errors


if __name__ == "__main__":
    resolve_trades()
