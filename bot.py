# =========================================================
# WEATHER QUANT BOT — BOT.PY COMPLETO
# =========================================================

import os
import time
import subprocess
import traceback
from datetime import datetime, timezone

# =========================================================
# UTC
# =========================================================

def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)

# =========================================================
# IMPORTS
# =========================================================

from gamma_parser import fetch_markets

from model import (
    calculate_probability,
    build_sigma,
)

from bankroll import (
    load_bankroll,
    save_bankroll,
    normalize_city,
    already_traded,
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
    MAX_TOTAL_EXPOSURE,
    MIN_MARKET_PRICE,
    MAX_MARKET_PRICE,
    MIN_LIQUIDITY_PRICE,
    MAX_LIQUIDITY_PRICE,
    MAX_EV,
)

from notificador import (
    notificar_entrada_trade,
    iniciar_listener,
)

from validacao import registrar_previsao

# =========================================================
# CONFIG
# =========================================================

MAX_POSITION_DOLARES = 10.0

# =========================================================
# RESET AUTOMÁTICO
# =========================================================

if os.getenv("RESET_BANKROLL") == "1":

    print("⚠️ RESETANDO BANKROLL...")

    reset_bankroll(50.0)

    print("✅ BANKROLL RESETADO")

# =========================================================
# SETTLEMENT
# =========================================================

def _rodar_settlement():

    from notificador import enviar_mensagem

    try:

        bot_dir = os.path.dirname(
            os.path.abspath(__file__)
        )

        res = subprocess.run(
            ["python", "settlement.py"],
            capture_output=True,
            text=True,
            timeout=90,
            cwd=bot_dir,
        )

        if res.returncode == 0:

            print("[scheduler] Settlement OK")

            enviar_mensagem(
                "Settlement diário executado com sucesso!"
            )

        else:

            erro = (
                res.stderr[:300]
                if res.stderr
                else "sem detalhes"
            )

            print(
                f"[scheduler] Settlement ERRO: {erro}"
            )

            enviar_mensagem(
                f"Erro no settlement diário:\n"
                f"<pre>{erro}</pre>"
            )

    except Exception as e:

        print(f"[scheduler] Exceção: {e}")

# =========================================================
# SCHEDULER
# =========================================================

def iniciar_scheduler():

    from threading import Thread

    def loop():

        HORARIOS_UTC = {8, 20}

        ultimo_dia = None
        ultima_hora = None

        print(
            "[scheduler] Agendador iniciado "
            "— settlement às 08:00 e 20:00 UTC"
        )

        while True:

            agora = utcnow()

            hora = agora.hour
            dia = agora.date()

            if hora in HORARIOS_UTC:

                chave = (dia, hora)

                if chave != (ultimo_dia, ultima_hora):

                    ultimo_dia = dia
                    ultima_hora = hora

                    print(
                        f"[scheduler] "
                        f"Disparando settlement — "
                        f"{agora.strftime('%Y-%m-%d %H:%M UTC')}"
                    )

                    _rodar_settlement()

            time.sleep(60)

    Thread(
        target=loop,
        daemon=True
    ).start()

# =========================================================
# EXACT GUARD
# =========================================================

def exact_market_guard(
    condition,
    model_prob,
    market_price,
    ev,
):

    if condition.upper() != "EXACT":
        return True

    if model_prob > 0.25:

        print(
            f"  🚫 EXACT bloqueado "
            f"(model_prob={model_prob:.3f})"
        )

        return False

    if ev > MAX_EV:

        print(
            f"  🚫 EXACT bloqueado "
            f"(EV={ev:.3f})"
        )

        return False

    if market_price < 0.10:

        print(
            f"  🚫 EXACT bloqueado "
            f"(price={market_price:.3f})"
        )

        return False

    return True

# =========================================================
# START
# =========================================================

iniciar_listener()
iniciar_scheduler()

# =========================================================
# LOOP PRINCIPAL
# =========================================================

while True:

    try:

        print("\n=======================")
        print("WEATHER QUANT CYCLE")
        print(
            f"  {utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )
        print("=======================")

        for city in CITY_SLUGS:

            bankroll = load_bankroll()

            balance = bankroll["balance"]
            history = bankroll["history"]

            current_exposure = open_exposure(history)

            remaining = remaining_capacity(history)

            print(
                f"\n[{city.upper()}] "
                f"Saldo: ${balance:.2f} | "
                f"Exposição: "
                f"${current_exposure:.2f} "
                f"/ "
                f"${MAX_TOTAL_EXPOSURE:.2f} | "
                f"Livre: ${remaining:.2f}"
            )

            if remaining <= 0:

                print(
                    f"  Exposição máxima atingida. "
                    f"Pulando {city}."
                )

                continue

            try:

                markets = fetch_markets(city)

                print(
                    f"  Mercados encontrados: "
                    f"{len(markets)}"
                )

                candidatos = []

                for market in markets:

                    try:

                        market_price = float(
                            market.get(
                                "yes_price",
                                market.get("price", 0)
                            )
                        )

                        # ==================================
                        # FILTER PRICE
                        # ==================================

                        if (
                            market_price < MIN_MARKET_PRICE
                            or
                            market_price > MAX_MARKET_PRICE
                        ):
                            continue

                        # ==================================
                        # LIQUIDEZ
                        # ==================================

                        if (
                            market_price
                            < MIN_LIQUIDITY_PRICE
                        ):

                            print(
                                f"  ⚠️ Liquidez baixa "
                                f"(price={market_price:.3f})"
                            )

                            continue

                        if (
                            market_price
                            > MAX_LIQUIDITY_PRICE
                        ):

                            print(
                                f"  ⚠️ Liquidez baixa "
                                f"(price={market_price:.3f})"
                            )

                            continue

                        market_id = str(
                            market.get("market_id", "")
                        )

                        condition = (
                            market.get(
                                "condition",
                                "ABOVE"
                            )
                            .upper()
                        )

                        unit = market.get("unit", "C")

                        target = float(
                            market.get("target", 0)
                        )

                        target_high = market.get(
                            "target_high"
                        )

                        if target_high is not None:
                            target_high = float(
                                target_high
                            )

                        # ==================================
                        # DATA
                        # ==================================

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

                                print(
                                    f"  ⏭️ Pulando "
                                    f"{market.get('question','')[:40]} "
                                    f"(hoje/passado)"
                                )

                                continue

                        except Exception as e:

                            print(
                                f"  ⚠️ Erro data: {e}"
                            )

                            continue

                        # ==================================
                        # DUPLICADO
                        # ==================================

                        history_ids = [
                            str(
                                t.get(
                                    "market_id",
                                    ""
                                )
                            )
                            for t in history
                        ]

                        if market_id in history_ids:
                            continue

                        # ==================================
                        # FORECAST DAY
                        # ==================================

                        try:

                            mdate = datetime.strptime(
                                market.get(
                                    "market_date",
                                    ""
                                ),
                                "%Y-%m-%d"
                            ).date()

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

                        except Exception:

                            forecast_day = 1

                        # ==================================
                        # FORECAST / SIGMA
                        # ==================================

                        forecast_c = market.get(
                            "forecast_c"
                        )

                        raw_sigma = market.get(
                            "raw_sigma",
                            1.8
                        )

                        # ==================================
                        # FALLBACK TEMPORÁRIO
                        # ==================================

                        if forecast_c is None:

                            forecast_c = target

                            print(
                                f"  ⚠️ forecast_c ausente "
                                f"→ fallback target={target}"
                            )

                        sigma_total = build_sigma(
                            city_slug=city,
                            forecast_day=forecast_day,
                            raw_sigma=raw_sigma,
                            condition=condition,
                        )

                        print(
                            f"  [Ensemble] {city} "
                            f"σ_total={sigma_total:.2f}"
                        )

                        # ==================================
                        # MODELO
                        # ==================================

                        try:

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

                        except Exception as e:

                            print(
                                f"  ⚠️ Erro modelo: {e}"
                            )

                            continue

                        if (
                            not model_prob
                            or model_prob <= 0
                            or model_prob >= 1
                        ):
                            continue

                        # ==================================
                        # EDGE / EV
                        # ==================================

                        edge = round(
                            model_prob - market_price,
                            4
                        )

                        ev = expected_value(
                            model_prob,
                            market_price
                        )

                        # ==================================
                        # GUARD EXACT
                        # ==================================

                        if not exact_market_guard(
                            condition,
                            model_prob,
                            market_price,
                            ev,
                        ):
                            continue

                        # ==================================
                        # LOG
                        # ==================================

                        print(
                            f"  {market.get('question','')[:60]} | "
                            f"Model:{model_prob:.3f} "
                            f"Mkt:{market_price:.3f} "
                            f"Edge:{edge:+.3f} "
                            f"EV:{ev:+.3f} "
                            f"[{unit}] "
                            f"[{condition}]"
                        )

                        edge_min = (
                            EDGE_THRESHOLD_EXACT
                            if condition == "EXACT"
                            else EDGE_THRESHOLD
                        )

                        if edge < edge_min:
                            continue

                        if ev > MAX_EV:

                            print(
                                f"  🚫 EV={ev:+.3f} "
                                f"acima do cap "
                                f"({MAX_EV})"
                            )

                            continue

                        event_slug = (
                            f"{city}_"
                            f"{market.get('market_date', '')}"
                        )

                        candidatos.append({

                            "market": market,

                            "market_price": market_price,

                            "model_prob": model_prob,

                            "edge": edge,

                            "ev": ev,

                            "event_slug": event_slug,

                            "condition": condition,

                            "unit": unit,

                            "target": target,

                            "target_high": target_high,

                            "forecast_day": forecast_day,

                            "market_id": market_id,
                        })

                    except Exception as e:

                        print(
                            f"  Erro avaliando market: {e}"
                        )

                # ==========================================
                # MELHOR POR EVENTO
                # ==========================================

                melhor_por_evento = {}

                for c in candidatos:

                    slug = c["event_slug"]

                    if (
                        slug not in melhor_por_evento
                        or
                        c["ev"]
                        > melhor_por_evento[slug]["ev"]
                    ):

                        melhor_por_evento[slug] = c

                selecionados = list(
                    melhor_por_evento.values()
                )

                descartados = (
                    len(candidatos)
                    - len(selecionados)
                )

                if descartados > 0:

                    print(
                        f"  ✂️ Sobreposição: "
                        f"{descartados} descartado(s)"
                    )

                if not selecionados:

                    print(
                        f"  Nenhum candidato válido "
                        f"para {city}."
                    )

                # ==========================================
                # EXECUÇÃO
                # ==========================================

                for cand in selecionados:

                    try:

                        market = cand["market"]

                        market_price = cand["market_price"]

                        model_prob = cand["model_prob"]

                        edge = cand["edge"]

                        ev = cand["ev"]

                        condition = cand["condition"]

                        unit = cand["unit"]

                        target = cand["target"]

                        forecast_day = cand["forecast_day"]

                        market_id = cand["market_id"]

                        bankroll = load_bankroll()

                        balance = bankroll["balance"]

                        history = bankroll["history"]

                        history_ids = [
                            str(
                                t.get(
                                    "market_id",
                                    ""
                                )
                            )
                            for t in history
                        ]

                        if market_id in history_ids:
                            continue

                        current_exposure = (
                            open_exposure(history)
                        )

                        remaining = (
                            remaining_capacity(history)
                        )

                        if remaining <= 0:

                            print(
                                f"  Capacidade esgotada "
                                f"para {city}."
                            )

                            break

                        print(
                            f"  → SELECIONADO: "
                            f"{market.get('question','')[:60]}"
                        )

                        # ==================================
                        # STAKE
                        # ==================================

                        stake = kelly_stake(
                            balance,
                            model_prob,
                            market_price
                        )

                        stake = cap_stake_by_type(
                            stake,
                            condition
                        )

                        if stake <= 0:

                            print(
                                f"  ⚠️ Kelly stake=0"
                            )

                            continue

                        stake = min(
                            stake,
                            remaining
                        )

                        if (
                            stake
                            > MAX_POSITION_DOLARES
                        ):
                            stake = (
                                MAX_POSITION_DOLARES
                            )

                        shares = int(
                            stake / market_price
                        )

                        if shares <= 0:

                            print(
                                f"  ⚠️ Shares=0 "
                                f"(stake=${stake:.2f})"
                            )

                            continue

                        real_cost = round(
                            shares * market_price,
                            2
                        )

                        stake = real_cost

                        if stake <= 0:
                            continue

                        city_display = normalize_city(
                            city
                        )

                        trade = {

                            "market_id": market_id,

                            "city": city_display,

                            "question": market.get(
                                "question",
                                ""
                            ),

                            "market_date": market.get(
                                "market_date",
                                ""
                            ),

                            "entry_time": utcnow().isoformat(),

                            "exit_time": None,

                            "type": condition,

                            "unit": unit,

                            "target": target,

                            "shares": shares,

                            "forecast_day": forecast_day,

                            "model_prob": round(
                                model_prob,
                                4
                            ),

                            "market_price": round(
                                market_price,
                                4
                            ),

                            "edge": edge,

                            "ev": ev,

                            "stake": stake,

                            "result": "OPEN",

                            "pnl": 0,

                            "fee": 0,

                            "real_temp_c": None,
                        }

                        bankroll["history"].append(
                            trade
                        )

                        bankroll["balance"] -= stake

                        balance = bankroll["balance"]

                        history = bankroll["history"]

                        save_bankroll(bankroll)

                        try:

                            registrar_previsao(

                                market_id=market_id,

                                city=city_display,

                                market_date=market.get(
                                    "market_date",
                                    ""
                                ),

                                target=target,

                                unit=unit,

                                condition=condition,

                                model_prob=model_prob,

                                market_price=market_price,

                                forecast_mean_c=None,

                                sigma_c=None,

                                edge=edge,

                                ev=ev,

                                stake=stake,

                                real_cost=real_cost,

                                shares=shares,
                            )

                        except Exception as e:

                            print(
                                f"  ⚠️ validacao.py erro: {e}"
                            )

                        print(
                            f"  >>> TRADE REGISTRADO\n"
                            f"  {city_display} | "
                            f"{condition} | "
                            f"Target:{target}°{unit}\n"
                            f"  Model:{model_prob:.3f} "
                            f"Mkt:{market_price:.3f} "
                            f"Edge:{edge:+.3f} "
                            f"EV:{ev:+.3f}\n"
                            f"  Shares:{shares} "
                            f"Stake:${stake:.2f} "
                            f"Saldo:${balance:.2f} "
                            f"Exposição:"
                            f"${open_exposure(history):.2f}"
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

                        except Exception as e:

                            print(
                                f"  ⚠️ Telegram erro: {e}"
                            )

                    except Exception as e:

                        print(
                            f"  Erro executando trade: {e}"
                        )

                        traceback.print_exc()

                time.sleep(1)

            except Exception as e:

                print(f"Erro city {city}: {e}")

        print("\nAguardando próximo ciclo (15min)...")

        time.sleep(900)

    except Exception as e:

        print(f"ERRO CRÍTICO LOOP: {e}")

        traceback.print_exc()

        print("Reiniciando em 30s...")

        time.sleep(30)
