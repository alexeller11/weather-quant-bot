# =========================================================
# WEATHER QUANT BOT — BOT.PY (COMPLETO)
# FIX #20: Guardrail model_prob == 0.50 exato
# FIX #21: balance/history carregados fora do loop de cidades
# FIX #22: scheduler roda settlement a cada hora
# =========================================================

import os
import time
import subprocess
import traceback

from datetime import (
    datetime,
    timezone,
)

# =========================================================
# UTC
# =========================================================

def utcnow():
    return datetime.now(
        timezone.utc
    ).replace(tzinfo=None)

# =========================================================
# IMPORTS
# =========================================================

from gamma_parser import fetch_markets

from forecast import get_forecast

from model import (
    calculate_probability,
    build_sigma,
    to_celsius,
)

from bankroll import (
    load_bankroll,
    save_bankroll,
    normalize_city,
    reset_bankroll,
)

from risk import (
    kelly_stake,
    expected_value,
    open_exposure,
    remaining_capacity,
    cap_stake_by_type,
)

from config import (

    CITY_SLUGS,

    EDGE_THRESHOLD,

    EDGE_THRESHOLD_EXACT,

    TRADING_ENABLED,

    PROBABILITY_DEAD_ZONE_LOW,
    PROBABILITY_DEAD_ZONE_HIGH,
    MIN_TARGET_ZSCORE,
    MIN_EV,

    MAX_TOTAL_EXPOSURE,
    MAX_POSITION,
    MAX_OPEN_TRADES,
    MAX_TRADES_PER_CYCLE,
    MAX_TRADES_PER_CITY,

    MIN_MARKET_PRICE,
    MAX_MARKET_PRICE,

    MIN_LIQUIDITY_PRICE,
    MAX_LIQUIDITY_PRICE,

    MAX_EV,

    CYCLE_INTERVAL_SECONDS,
)

from notificador import (
    notificar_entrada_trade,
    iniciar_listener,
)

# =========================================================
# CONFIG
# =========================================================

MAX_POSITION_DOLARES = MAX_POSITION

# =========================================================
# RESET
# =========================================================

if os.getenv("RESET_BANKROLL") == "1":

    print(
        "⚠️ RESETANDO BANKROLL..."
    )

    reset_bankroll(50.0)

    print(
        "✅ BANKROLL RESETADO"
    )

# =========================================================
# SETTLEMENT
# =========================================================

def _rodar_settlement():

    from notificador import (
        enviar_mensagem
    )

    try:

        bot_dir = os.path.dirname(
            os.path.abspath(__file__)
        )

        res = subprocess.run(
            ["python", "settlement.py"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=bot_dir,
        )

        if res.returncode == 0:

            print(
                "[scheduler] Settlement OK"
            )

            if "Resolvidos agora:  0" not in (res.stdout or ""):
                enviar_mensagem(
                    "Settlement executado com sucesso!"
                )

        else:

            erro = (
                res.stderr[:300]
                if res.stderr
                else "sem detalhes"
            )

            print(
                f"[scheduler] "
                f"Settlement ERRO: {erro}"
            )

    except Exception as e:

        print(
            f"[scheduler] Exceção: {e}"
        )

# =========================================================
# SCHEDULER — roda settlement a cada hora
# =========================================================

def iniciar_scheduler():

    from threading import Thread

    def loop():

        ultimo_settlement = None

        print(
            "[scheduler] "
            "Agendador iniciado — settlement a cada hora"
        )

        while True:

            agora = utcnow()
            hora_atual = (agora.date(), agora.hour)

            if hora_atual != ultimo_settlement:

                ultimo_settlement = hora_atual

                print(
                    f"[scheduler] "
                    f"Settlement "
                    f"{agora.strftime('%Y-%m-%d %H:%M UTC')}"
                )

                _rodar_settlement()

            time.sleep(60)

    Thread(
        target=loop,
        daemon=True
    ).start()

# =========================================================
# EXACT GUARD (RELAXADO)
# =========================================================

def exact_market_guard(
    condition,
    model_prob,
    market_price,
    ev,
):

    if condition.upper() != "EXACT":
        return True

    if market_price > 0.30:

        print(
            "  🚫 EXACT caro demais"
        )

        return False

    if model_prob > 0.30:

        print(
            f"  🚫 EXACT bloqueado "
            f"(prob={model_prob:.3f})"
        )

        return False

    if ev > MAX_EV:

        print(
            f"  🚫 EXACT bloqueado "
            f"(ev={ev:.3f})"
        )

        return False

    if market_price < 0.10:

        print(
            f"  🚫 EXACT bloqueado "
            f"(price={market_price:.3f})"
        )

        return False

    exact_edge = (
        model_prob
        - market_price
    )

    if exact_edge < 0.07:

        print(
            f"  🚫 EXACT edge fraco "
            f"({exact_edge:.3f})"
        )

        return False

    ratio = (
        model_prob
        / max(market_price, 0.01)
    )

    if ratio > 3.5:

        print(
            f"  🚫 EXACT distorcido "
            f"(ratio={ratio:.2f})"
        )

        return False

    return True

# =========================================================
# GENERAL TRADE GUARD
# =========================================================

def trade_quality_guard(
    condition,
    forecast_c,
    sigma_total,
    target,
    unit,
    model_prob,
    market_price,
    ev,
):

    condition = condition.upper()

    if PROBABILITY_DEAD_ZONE_LOW <= model_prob <= PROBABILITY_DEAD_ZONE_HIGH:
        print(
            f"  BLOQUEADO prob neutra "
            f"({model_prob:.4f})"
        )
        return False

    if ev < MIN_EV or ev > MAX_EV:
        print(
            f"  BLOQUEADO EV fora da faixa "
            f"({ev:.4f})"
        )
        return False

    if market_price <= 0 or market_price >= 1:
        return False

    target_c = to_celsius(target, unit)
    zscore = abs(float(forecast_c) - target_c) / max(float(sigma_total), 0.10)

    if condition in ("ABOVE", "BELOW") and zscore < MIN_TARGET_ZSCORE:
        print(
            f"  BLOQUEADO target perto do forecast "
            f"(z={zscore:.2f})"
        )
        return False

    return True

# =========================================================
# START
# =========================================================

iniciar_listener()
iniciar_scheduler()

# =========================================================
# MAIN LOOP
# =========================================================

while True:

    try:

        print("\n=======================")

        print(
            "WEATHER QUANT CYCLE"
        )

        print(
            utcnow().strftime(
                "%Y-%m-%d %H:%M:%S UTC"
            )
        )

        print("=======================")

        bankroll = load_bankroll()
        balance  = bankroll["balance"]
        history  = bankroll["history"]

        if not TRADING_ENABLED:
            print(
                "TRADING_ENABLED=0 - modo observacao, "
                "nenhuma entrada nova sera aberta."
            )
            save_bankroll(bankroll)
            time.sleep(CYCLE_INTERVAL_SECONDS)
            continue

        trades_opened_cycle = 0

        for city in CITY_SLUGS:

            if trades_opened_cycle >= MAX_TRADES_PER_CYCLE:
                print("  Limite de entradas do ciclo atingido")
                break

            opened_this_cycle = len([
                t for t in history
                if t.get("result") == "OPEN"
            ])

            if opened_this_cycle >= MAX_OPEN_TRADES:
                print("  Limite de trades abertos atingido")
                break

            current_exposure = (
                open_exposure(history)
            )

            remaining = (
                remaining_capacity(history)
            )

            print(
                f"\n[{city.upper()}] "
                f"Saldo:${balance:.2f} "
                f"Exposição:"
                f"${current_exposure:.2f}/"
                f"${MAX_TOTAL_EXPOSURE:.2f}"
            )

            if remaining <= 0:

                print(
                    "  Exposição máxima"
                )

                continue

            try:

                markets = fetch_markets(
                    city
                )

                print(
                    f"  Markets:"
                    f"{len(markets)}"
                )

                candidatos = []

                for market in markets:

                    try:

                        market_price = float(
                            market.get(
                                "yes_price",
                                market.get(
                                    "price",
                                    0
                                )
                            )
                        )

                        if (
                            market_price
                            < MIN_MARKET_PRICE
                            or
                            market_price
                            > MAX_MARKET_PRICE
                        ):
                            continue

                        if (
                            market_price
                            < MIN_LIQUIDITY_PRICE
                        ):
                            continue

                        if (
                            market_price
                            > MAX_LIQUIDITY_PRICE
                        ):
                            continue

                        market_id = str(
                            market.get(
                                "market_id",
                                ""
                            )
                        )

                        condition = (
                            market.get(
                                "condition",
                                "ABOVE"
                            ).upper()
                        )

                        unit = market.get(
                            "unit",
                            "C"
                        )

                        target = float(
                            market.get(
                                "target",
                                0
                            )
                        )

                        try:

                            market_date_obj = (
                                datetime.strptime(
                                    market.get(
                                        "market_date",
                                        ""
                                    ),
                                    "%Y-%m-%d"
                                ).date()
                            )

                            if (
                                market_date_obj
                                <= utcnow().date()
                            ):
                                continue

                        except:
                            continue

                        history_ids = [

                            str(
                                t.get(
                                    "market_id",
                                    ""
                                )
                            )

                            for t in history
                        ]

                        if (
                            market_id
                            in history_ids
                        ):
                            continue

                        try:

                            mdate = (
                                datetime.strptime(
                                    market.get(
                                        "market_date",
                                        ""
                                    ),
                                    "%Y-%m-%d"
                                ).date()
                            )

                            forecast_day = max(

                                1,

                                min(
                                    (
                                        mdate
                                        - utcnow().date()
                                    ).days,
                                    5
                                )
                            )

                        except:

                            forecast_day = 1

                        forecast_c, raw_sigma = (
                            get_forecast(
                                city,
                                forecast_day
                            )
                        )

                        if (
                            forecast_c is None
                        ):

                            print(
                                "  Forecast indisponível"
                            )

                            continue

                        print(
                            f"  [Forecast] "
                            f"{city} "
                            f"day={forecast_day} "
                            f"temp={forecast_c:.1f}C "
                            f"sigma={raw_sigma:.2f}"
                        )

                        sigma_total = (
                            build_sigma(
                                city_slug=city,
                                forecast_day=forecast_day,
                                raw_sigma=raw_sigma,
                                condition=condition,
                            )
                        )

                        if sigma_total is None:
                            continue

                        print(
                            f"  [Sigma] "
                            f"{sigma_total:.2f}"
                        )

                        model_prob = (
                            calculate_probability(

                                forecast_c=float(
                                    forecast_c
                                ),

                                sigma=float(
                                    sigma_total
                                ),

                                target=target,

                                condition=condition,

                                unit=unit,
                            )
                        )

                        if (
                            model_prob <= 0
                            or
                            model_prob >= 1
                        ):
                            continue

                        edge = round(
                            (
                                model_prob
                                - market_price
                            ),
                            4
                        )

                        ev = expected_value(
                            model_prob,
                            market_price
                        )

                        if not exact_market_guard(
                            condition,
                            model_prob,
                            market_price,
                            ev,
                        ):
                            continue

                        if not trade_quality_guard(
                            condition=condition,
                            forecast_c=forecast_c,
                            sigma_total=sigma_total,
                            target=target,
                            unit=unit,
                            model_prob=model_prob,
                            market_price=market_price,
                            ev=ev,
                        ):
                            continue

                        print(
                            f"  Model:"
                            f"{model_prob:.3f} "
                            f"Mkt:"
                            f"{market_price:.3f} "
                            f"Edge:"
                            f"{edge:+.3f} "
                            f"EV:"
                            f"{ev:+.3f} "
                            f"[{condition}]"
                        )

                        edge_min = (
                            EDGE_THRESHOLD_EXACT
                            if condition == "EXACT"
                            else EDGE_THRESHOLD
                        )

                        if edge < edge_min:
                            continue

                        candidatos.append({

                            "market": market,

                            "market_price": market_price,

                            "model_prob": model_prob,

                            "edge": edge,

                            "ev": ev,

                            "condition": condition,

                            "target": target,

                            "forecast_day": forecast_day,

                            "forecast_c": forecast_c,

                            "sigma_total": sigma_total,

                            "market_id": market_id,

                            "unit": unit,
                        })

                    except Exception as e:

                        print(
                            f"Erro market: {e}"
                        )

                candidatos = sorted(
                    candidatos,
                    key=lambda x: (
                        x["edge"],
                        x["ev"],
                    ),
                    reverse=True,
                )[:MAX_TRADES_PER_CITY]

                for cand in candidatos:

                    try:

                        market = cand["market"]

                        market_price = cand[
                            "market_price"
                        ]

                        model_prob = cand[
                            "model_prob"
                        ]

                        edge = cand["edge"]

                        ev = cand["ev"]

                        condition = cand[
                            "condition"
                        ]

                        target = cand["target"]

                        market_id = cand[
                            "market_id"
                        ]

                        forecast_c = cand[
                            "forecast_c"
                        ]

                        sigma_total = cand[
                            "sigma_total"
                        ]

                        unit = cand["unit"]

                        remaining = (
                            remaining_capacity(
                                history
                            )
                        )

                        if remaining <= 0:
                            break

                        open_count = len([
                            t for t in history
                            if t.get("result") == "OPEN"
                        ])

                        if open_count >= MAX_OPEN_TRADES:
                            break

                        if trades_opened_cycle >= MAX_TRADES_PER_CYCLE:
                            break

                        print(
                            f"  → TRADE "
                            f"{market.get('question','')[:60]}"
                        )

                        stake = kelly_stake(
                            balance,
                            model_prob,
                            market_price
                        )

                        stake = (
                            cap_stake_by_type(
                                stake,
                                condition
                            )
                        )

                        if stake <= 0:
                            continue

                        stake = min(stake, remaining)

                        if stake > MAX_POSITION_DOLARES:
                            stake = MAX_POSITION_DOLARES

                        shares = int(
                            stake / market_price
                        )

                        if shares <= 0:
                            continue

                        real_cost = round(
                            shares * market_price,
                            2
                        )

                        stake = real_cost

                        city_display = (
                            normalize_city(
                                city
                            )
                        )

                        trade = {

                            "market_id":
                            market_id,

                            "city":
                            city_display,

                            "question":
                            market.get(
                                "question",
                                ""
                            ),

                            "market_date":
                            market.get(
                                "market_date",
                                ""
                            ),

                            "entry_time":
                            utcnow().isoformat(),

                            "exit_time":
                            None,

                            "type":
                            condition,

                            "target":
                            target,

                            "forecast_c":
                            forecast_c,

                            "sigma_total":
                            sigma_total,

                            "shares":
                            shares,

                            "model_prob":
                            round(
                                model_prob,
                                4
                            ),

                            "market_price":
                            round(
                                market_price,
                                4
                            ),

                            "edge":
                            edge,

                            "ev":
                            ev,

                            "stake":
                            stake,

                            "result":
                            "OPEN",

                            "pnl":
                            0,

                            "unit": unit,
                        }

                        history.append(
                            trade
                        )

                        trades_opened_cycle += 1

                        balance -= stake

                        print(
                            f"  >>> TRADE "
                            f"REGISTRADO "
                            f"${stake:.2f}"
                        )

                        try:

                            notificar_entrada_trade(

                                city=city_display,

                                market_date=market.get(
                                    "market_date",
                                    ""
                                ),

                                target=target,

                                unit=unit,

                                stake=stake,

                                model_prob=model_prob,

                                market_price=market_price,

                                edge=edge * 100,

                                balance=balance,

                                shares=shares,
                            )

                            print(
                                "  Telegram enviado"
                            )

                        except Exception as e:

                            print(
                                f"Telegram erro: {e}"
                            )

                    except Exception as e:

                        print(
                            f"Erro trade: {e}"
                        )

                        traceback.print_exc()

            except Exception as e:

                print(
                    f"Erro city {city}: {e}"
                )

        bankroll["balance"] = balance
        save_bankroll(bankroll)

        print(
            f"\nPróximo ciclo em {CYCLE_INTERVAL_SECONDS}s..."
        )

        time.sleep(CYCLE_INTERVAL_SECONDS)

    except Exception as e:

        print(
            f"ERRO LOOP: {e}"
        )

        traceback.print_exc()

        time.sleep(30)
