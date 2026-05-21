import time
import subprocess
from datetime import datetime, timezone, timedelta

def utcnow():
    """Substitui utcnow() depreciado no Python 3.12+."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

from gamma_parser import fetch_markets
from model import calculate_probability
from bankroll import load_bankroll, save_bankroll, normalize_city, already_traded
from risk import kelly_stake, expected_value, open_exposure
from config import (
    CITY_SLUGS,
    EDGE_THRESHOLD,
    MAX_TOTAL_EXPOSURE,
    MIN_MARKET_PRICE,
    MAX_MARKET_PRICE,
    MIN_LIQUIDITY_PRICE,
    MAX_LIQUIDITY_PRICE,
    MAX_EV,
    CITY_MIN_SIGMA,
)

from notificador import notificar_entrada_trade, iniciar_listener
from validacao import registrar_previsao

# ==========================================
# CONFIGURAÇÃO
# ==========================================

MAX_POSITION_DOLARES = 10.0  # Máximo $10 por trade

# ==========================================
# AGENDAMENTO AUTOMÁTICO
# ==========================================

def _rodar_settlement():
    """Executa settlement.py e notifica resultado."""
    import os
    from notificador import enviar_mensagem
    try:
        bot_dir = os.path.dirname(os.path.abspath(__file__))
        res = subprocess.run(
            ["python", "settlement.py"],
            capture_output=True, text=True, timeout=90, cwd=bot_dir,
        )
        if res.returncode == 0:
            print("[scheduler] Settlement OK")
            enviar_mensagem("Settlement diário executado com sucesso!")
        else:
            erro = res.stderr[:300] if res.stderr else "sem detalhes"
            print(f"[scheduler] Settlement ERRO: {erro}")
            enviar_mensagem(f"Erro no settlement diário:\n<pre>{erro}</pre>")
    except Exception as e:
        print(f"[scheduler] Exceção: {e}")


def iniciar_scheduler():
    """
    Roda settlement automaticamente todo dia às 08:00 UTC e às 20:00 UTC.
    """
    from threading import Thread

    def loop():
        HORARIOS_UTC = {8, 20}
        ultimo_dia   = None
        ultima_hora  = None

        print("[scheduler] Agendador iniciado — settlement às 08:00 e 20:00 UTC")
        while True:
            agora = utcnow()
            hora  = agora.hour
            dia   = agora.date()

            if hora in HORARIOS_UTC:
                chave = (dia, hora)
                if chave != (ultimo_dia, ultima_hora):
                    ultimo_dia  = dia
                    ultima_hora = hora
                    print(f"[scheduler] Disparando settlement — {agora.strftime('%Y-%m-%d %H:%M UTC')}")
                    _rodar_settlement()

            time.sleep(60)

    Thread(target=loop, daemon=True).start()


iniciar_listener()
iniciar_scheduler()


# ==========================================
# LOOP PRINCIPAL
# ==========================================

while True:

    try:

        print("\n=======================")
        print("WEATHER QUANT CYCLE")
        print(f"  {utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
        print("=======================")

        for city in CITY_SLUGS:

            bankroll = load_bankroll()
            balance  = bankroll["balance"]
            history  = bankroll["history"]

            current_exposure = open_exposure(history)
            max_allowed      = MAX_TOTAL_EXPOSURE

            print(
                f"\n[{city.upper()}] "
                f"Saldo: ${balance:.2f} | "
                f"Exposição: ${current_exposure:.2f} / ${max_allowed:.2f}"
            )

            if current_exposure >= max_allowed:
                print(f"  Exposição máxima atingida. Pulando {city}.")
                continue

            try:
                markets = fetch_markets(city)
                print(f"  Mercados encontrados: {len(markets)}")

                # ── PRÉ-SELEÇÃO: 1 trade por evento (cidade+data) ────────────
                # Passo 1: avalia TODOS os mercados e calcula edge/EV
                # Passo 2: por event_slug, mantém só o de MAIOR EV
                # Isso garante que Seoul 23°C e 24°C nunca entram juntos

                candidatos = []

                for market in markets:
                    try:
                        market_price = float(market.get("yes_price", market.get("price", 0)))

                        if market_price < MIN_MARKET_PRICE or market_price > MAX_MARKET_PRICE:
                            continue
                        if market_price < MIN_LIQUIDITY_PRICE:
                            print(f"  ⚠️  Liquidez baixa (price={market_price:.3f}). Pulando.")
                            continue
                        if market_price > MAX_LIQUIDITY_PRICE:
                            print(f"  ⚠️  Liquidez baixa (price={market_price:.3f}). Pulando.")
                            continue

                        market_id   = market.get("market_id")
                        condition   = market.get("condition", "ABOVE").upper()
                        unit        = market.get("unit", "C")
                        target      = float(market.get("target", 0))
                        target_high = market.get("target_high")
                        if target_high is not None:
                            target_high = float(target_high)

                        # Filtro D1+: só entra para amanhã ou depois
                        try:
                            market_date_obj = datetime.strptime(
                                market.get("market_date", ""), "%Y-%m-%d"
                            ).date()
                            if market_date_obj <= utcnow().date():
                                print(f"  ⏭️  Pulando {market.get('question','')[:40]} (hoje ou passado)")
                                continue
                        except Exception as e:
                            print(f"  ⚠️  Erro data: {e}")
                            continue

                        # Anti-duplicata
                        if already_traded(history, market_id):
                            continue

                        # Horizonte de forecast
                        try:
                            mdate        = datetime.strptime(market.get("market_date", ""), "%Y-%m-%d").date()
                            forecast_day = max(0, min((mdate - utcnow().date()).days, 3))
                        except Exception:
                            forecast_day = 1

                        # Modelo probabilístico
                        try:
                            model_prob = calculate_probability(
                                city=city,
                                target=target,
                                unit=unit,
                                forecast_day=forecast_day,
                                condition=condition.lower(),
                                target_high=target_high,
                            )
                        except Exception as e:
                            print(f"  ⚠️  Erro no modelo: {e}")
                            continue

                        if not model_prob or model_prob <= 0 or model_prob >= 1:
                            continue

                        edge = round(model_prob - market_price, 4)
                        ev   = expected_value(model_prob, market_price)

                        print(
                            f"  {market.get('question','')[:60]} | "
                            f"Model:{model_prob:.3f} Mkt:{market_price:.3f} "
                            f"Edge:{edge:+.3f} EV:{ev:+.3f} [{unit}]"
                        )

                        if edge < EDGE_THRESHOLD:
                            continue

                        if ev > MAX_EV:
                            print(f"  🚫 EV={ev:+.3f} acima do cap ({MAX_EV}). Pulando.")
                            continue

                        event_slug = f"{city}_{market.get('market_date', '')}"

                        candidatos.append({
                            "market":        market,
                            "market_price":  market_price,
                            "model_prob":    model_prob,
                            "edge":          edge,
                            "ev":            ev,
                            "event_slug":    event_slug,
                            "condition":     condition,
                            "unit":          unit,
                            "target":        target,
                            "target_high":   target_high,
                            "forecast_day":  forecast_day,
                            "market_id":     market_id,
                        })

                    except Exception as e:
                        print(f"  Erro avaliando market: {e}")

                # Passo 2: por event_slug, mantém só o de maior EV
                melhor_por_evento: dict = {}
                for c in candidatos:
                    slug = c["event_slug"]
                    if slug not in melhor_por_evento or c["ev"] > melhor_por_evento[slug]["ev"]:
                        melhor_por_evento[slug] = c

                selecionados = list(melhor_por_evento.values())

                descartados = len(candidatos) - len(selecionados)
                if descartados > 0:
                    print(f"  ✂️  Sobreposição: {descartados} outcome(s) descartado(s) — {len(selecionados)} selecionado(s)")

                # ── EXECUÇÃO dos trades selecionados ─────────────────────────
                for cand in selecionados:

                    try:
                        market       = cand["market"]
                        market_price = cand["market_price"]
                        model_prob   = cand["model_prob"]
                        edge         = cand["edge"]
                        ev           = cand["ev"]
                        condition    = cand["condition"]
                        unit         = cand["unit"]
                        target       = cand["target"]
                        target_high  = cand["target_high"]
                        forecast_day = cand["forecast_day"]
                        market_id    = cand["market_id"]

                        # Recarrega bankroll fresco antes de cada execução
                        bankroll = load_bankroll()
                        balance  = bankroll["balance"]
                        history  = bankroll["history"]

                        # Anti-duplicata (pode ter sido executado em ciclo anterior)
                        if already_traded(history, market_id):
                            continue

                        # Capacidade restante
                        current_exposure   = open_exposure(history)
                        remaining_capacity = max_allowed - current_exposure
                        if remaining_capacity <= 0:
                            print(f"  Capacidade esgotada para {city}.")
                            break

                        print(f"  → SELECIONADO: {market.get('question','')[:60]}")

                        stake = kelly_stake(balance, model_prob, market_price)
                        if stake <= 0:
                            continue

                        stake = min(stake, remaining_capacity)
                        if stake > MAX_POSITION_DOLARES:
                            stake = MAX_POSITION_DOLARES

                        shares    = int(stake / market_price)
                        if shares <= 0:
                            continue
                        real_cost = round(shares * market_price, 2)
                        stake     = real_cost

                        if stake <= 0:
                            continue

                        city_display = normalize_city(city)

                        trade = {
                            "market_id":    market_id,
                            "city":         city_display,
                            "question":     market.get("question", ""),
                            "market_date":  market.get("market_date", ""),
                            "entry_time":   utcnow().isoformat(),
                            "exit_time":    None,
                            "type":         condition,
                            "unit":         unit,
                            "target":       target,
                            "target_high":  target_high,
                            "shares":       shares,
                            "forecast_day": forecast_day,
                            "model_prob":   round(model_prob, 4),
                            "market_price": round(market_price, 4),
                            "edge":         edge,
                            "ev":           ev,
                            "stake":        stake,
                            "result":       "OPEN",
                            "pnl":          0,
                            "fee":          0,
                            "real_temp_c":  None,
                        }

                        bankroll["history"].append(trade)
                        bankroll["balance"] -= stake
                        balance = bankroll["balance"]
                        history = bankroll["history"]

                        save_bankroll(bankroll)

                        try:
                            registrar_previsao(
                                market_id=market_id,
                                city=city_display,
                                market_date=market.get("market_date", ""),
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
                            print(f"  ⚠️  validacao.py erro: {e}")

                        print(
                            f"  >>> TRADE EXECUTADO\n"
                            f"  {city_display} | {condition} | Target:{target}°{unit}\n"
                            f"  Model:{model_prob:.3f} Mkt:{market_price:.3f} "
                            f"Edge:{edge:+.3f} EV:{ev:+.3f}\n"
                            f"  Shares:{shares} Stake:${stake:.2f} Saldo:${balance:.2f}"
                        )

                        try:
                            notificar_entrada_trade(
                                city=city_display,
                                market_date=market.get("market_date", ""),
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
                            print(f"  ⚠️  Erro Telegram: {e}")

                    except Exception as e:
                        print(f"  Erro executando trade: {e}")
                        import traceback
                        traceback.print_exc()

                time.sleep(1)

            except Exception as e:
                print(f"Erro city {city}: {e}")

        print("\nAguardando próximo ciclo (15min)...")
        time.sleep(900)

    except Exception as e:
        print(f"ERRO CRÍTICO LOOP: {e}")
        import traceback
        traceback.print_exc()
        print("Reiniciando em 30s...")
        time.sleep(30)
