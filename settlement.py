import requests
import json
from datetime import datetime, timezone, timedelta

def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)

from bankroll import load_bankroll, save_bankroll

try:
    from validacao import (
        registrar_resultado,
        gerar_relatorio
    )

    VALIDACAO_OK = True

except Exception:

    VALIDACAO_OK = False

from config import (
    POLYMARKET_FEE,
    CITY_COORDS_BY_SLUG,
    CITY_SLUG_NORMALIZE
)

# =========================================================
# TELEGRAM
# =========================================================

try:

    from notificador import (
        notificar_settlement_win,
        notificar_settlement_loss,
        notificar_settlement_resumo,
    )

    TELEGRAM_OK = True

except Exception as e:

    print(
        f"⚠️ Telegram indisponível: {e}"
    )

    TELEGRAM_OK = False

    def notificar_settlement_win(*a, **kw):
        pass

    def notificar_settlement_loss(*a, **kw):
        pass

    def notificar_settlement_resumo(*a, **kw):
        pass

# =========================================================
# LOG
# =========================================================

LOG_FILE = "settlement.log"

def log_settlement(msg):

    ts = utcnow().isoformat()

    line = f"[{ts}] {msg}"

    print(line)

    with open(
        LOG_FILE,
        "a",
        encoding="utf-8"
    ) as f:

        f.write(line + "\n")

# =========================================================
# CITY → SLUG
# =========================================================

def _to_slug(city_raw):

    key = (
        city_raw.lower()
        .replace(" ", "-")
        .replace("_", "-")
        .strip()
    )

    if key in CITY_COORDS_BY_SLUG:
        return key

    key2 = (
        city_raw.lower()
        .replace("-", " ")
        .strip()
    )

    slug = (
        CITY_SLUG_NORMALIZE.get(key)
        or
        CITY_SLUG_NORMALIZE.get(key2)
    )

    return slug

# =========================================================
# WEATHER
# =========================================================

def get_real_temperature(
    city_raw,
    date
):

    slug = _to_slug(city_raw)

    if (
        not slug
        or slug not in CITY_COORDS_BY_SLUG
    ):

        log_settlement(
            f"❌ Cidade desconhecida: "
            f"{city_raw}"
        )

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

        r = requests.get(
            url,
            timeout=20
        )

        data = r.json()

        if "daily" not in data:

            log_settlement(
                f"❌ Sem dados "
                f"{city_raw} {date}"
            )

            return None

        temps = data["daily"].get(
            "temperature_2m_max",
            []
        )

        if (
            not temps
            or temps[0] is None
        ):

            log_settlement(
                f"❌ Temperatura NULL "
                f"{city_raw} {date}"
            )

            return None

        return float(temps[0])

    except Exception as e:

        log_settlement(
            f"❌ Weather API: {e}"
        )

        return None

# =========================================================
# CONVERSÃO
# =========================================================

def to_celsius(
    value,
    unit
):

    if (
        unit
        and str(unit).upper() == "F"
    ):

        return (
            (float(value) - 32.0)
            * 5.0 / 9.0
        )

    return float(value)

# =========================================================
# READY TO SETTLE
# =========================================================

def can_settle_trade(
    trade_date
):

    now = utcnow()

    # resolve somente após
    # 12:00 UTC do dia seguinte

    settle_after = datetime.combine(
        trade_date + timedelta(days=1),
        datetime.min.time()
    ) + timedelta(hours=12)

    return now >= settle_after

# =========================================================
# SETTLEMENT
# =========================================================

def resolve_trades():

    log_settlement("=" * 60)

    log_settlement(
        "🚀 INICIANDO SETTLEMENT"
    )

    log_settlement(
        f"UTC NOW: {utcnow().isoformat()}"
    )

    bankroll = load_bankroll()

    history = bankroll["history"]

    updated = 0

    errors = 0

    session_wins = 0

    session_losses = 0

    session_pnl = 0.0

    open_trades = [

        t for t in history

        if t.get("result") == "OPEN"
    ]

    log_settlement(
        f"OPEN trades: {len(open_trades)}"
    )

    for trade in open_trades:

        try:

            market_id = trade.get(
                "market_id",
                "?"
            )

            city = trade.get(
                "city",
                ""
            )

            target = trade.get(
                "target"
            )

            market_date = trade.get(
                "market_date"
            )

            trade_type = trade.get(
                "type",
                "ABOVE"
            )

            unit = trade.get(
                "unit",
                "C"
            )

            if (
                not city
                or not market_date
                or target is None
            ):

                log_settlement(
                    f"⚠️ Trade inválido "
                    f"{trade}"
                )

                errors += 1

                continue

            trade_date = datetime.strptime(
                market_date,
                "%Y-%m-%d"
            ).date()

            # =================================================
            # FIX PRINCIPAL
            # =================================================

            if not can_settle_trade(
                trade_date
            ):

                log_settlement(
                    f"⏳ Ainda não resolve "
                    f"{city} {market_date}"
                )

                continue

            log_settlement(
                f"🔍 Resolvendo "
                f"{city} {market_date}"
            )

            real_temp_c = get_real_temperature(
                city,
                market_date
            )

            if real_temp_c is None:

                log_settlement(
                    f"⚠️ Sem temperatura "
                    f"{city} {market_date}"
                )

                errors += 1

                continue

            trade["real_temp_c"] = round(
                real_temp_c,
                2
            )

            target_c = to_celsius(
                target,
                unit
            )

            stake = float(
                trade.get("stake", 0)
            )

            market_price = float(
                trade.get(
                    "market_price",
                    0
                )
            )

            if (
                market_price <= 0
                or stake <= 0
            ):

                log_settlement(
                    f"⚠️ Valores inválidos"
                )

                errors += 1

                continue

            # =================================================
            # RESULTADO
            # =================================================

            if trade_type == "ABOVE":

                win = (
                    real_temp_c >= target_c
                )

            elif trade_type == "BELOW":

                win = (
                    real_temp_c <= target_c
                )

            else:

                log_settlement(
                    f"⚠️ Tipo inválido"
                )

                errors += 1

                continue

            if win:

                gross_payout = (
                    stake / market_price
                )

                fee = (
                    (gross_payout - stake)
                    * POLYMARKET_FEE
                )

                payout = (
                    gross_payout - fee
                )

                pnl = payout - stake

                bankroll["balance"] += payout

                trade["result"] = "WIN"

                trade["pnl"] = round(
                    pnl,
                    2
                )

                trade["fee"] = round(
                    fee,
                    2
                )

                session_wins += 1

                session_pnl += pnl

                result_str = "✅ WIN"

                try:

                    notificar_settlement_win(
                        city=city,
                        market_date=market_date,
                        target=target,
                        unit=unit,
                        stake=stake,
                        pnl=round(pnl, 2),
                        saldo=round(
                            bankroll["balance"],
                            2
                        ),
                        model_prob=trade.get(
                            "model_prob"
                        ),
                        real_temp_c=real_temp_c,
                    )

                except Exception as e:

                    log_settlement(
                        f"Telegram WIN: {e}"
                    )

            else:

                trade["result"] = "LOSS"

                trade["pnl"] = round(
                    -stake,
                    2
                )

                trade["fee"] = 0.0

                session_losses += 1

                session_pnl -= stake

                result_str = "❌ LOSS"

                try:

                    notificar_settlement_loss(
                        city=city,
                        market_date=market_date,
                        target=target,
                        unit=unit,
                        stake=stake,
                        pnl=round(-stake, 2),
                        saldo=round(
                            bankroll["balance"],
                            2
                        ),
                        model_prob=trade.get(
                            "model_prob"
                        ),
                        real_temp_c=real_temp_c,
                    )

                except Exception as e:

                    log_settlement(
                        f"Telegram LOSS: {e}"
                    )

            trade["exit_time"] = (
                utcnow().isoformat()
            )

            updated += 1

            log_settlement(
                f"{result_str} | "
                f"{city} | "
                f"{market_date} | "
                f"Real {real_temp_c:.1f}°C | "
                f"Target {target_c:.1f}°C | "
                f"PnL ${trade['pnl']:+.2f}"
            )

        except Exception as e:

            log_settlement(
                f"❌ ERRO: {e}"
            )

            import traceback

            log_settlement(
                traceback.format_exc()
            )

            errors += 1

    save_bankroll(bankroll)

    total_wins = sum(
        1 for t in history
        if t.get("result") == "WIN"
    )

    total_losses = sum(
        1 for t in history
        if t.get("result") == "LOSS"
    )

    total_pnl = sum(
        t.get("pnl", 0)
        for t in history
        if t.get("result")
        in ("WIN", "LOSS")
    )

    log_settlement("=" * 60)

    log_settlement(
        f"✅ Resolvidos: {updated}"
    )

    log_settlement(
        f"❌ Erros: {errors}"
    )

    log_settlement(
        f"📈 Total: "
        f"{total_wins}W/"
        f"{total_losses}L"
    )

    log_settlement(
        f"💰 PnL: "
        f"${total_pnl:+.2f}"
    )

    log_settlement(
        f"💵 Saldo: "
        f"${bankroll['balance']:.2f}"
    )

    log_settlement("=" * 60)

    if updated > 0:

        try:

            notificar_settlement_resumo(
                total_resolved=updated,
                wins=session_wins,
                losses=session_losses,
                total_pnl=round(
                    session_pnl,
                    2
                ),
                saldo=round(
                    bankroll["balance"],
                    2
                ),
            )

        except Exception as e:

            log_settlement(
                f"Telegram resumo: {e}"
            )

    return updated, errors

# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    resolve_trades()
