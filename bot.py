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

# FIX: import do notificador.py (renomeado de telegram.py para evitar
# colisão com o pacote pip 'python-telegram-bot').
# Sem try/except silencioso — se falhar, queremos saber o motivo.
from notificador import notificar_entrada_trade, iniciar_listener
from validacao import registrar_previsao

# ==========================================
# CONFIGURAÇÃO
# ==========================================

MAX_POSITION_DOLARES = 5.0   # Máximo $5 por trade

# ==========================================
# INICIALIZAÇÃO
# ==========================================

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
    Roda em thread daemon — não bloqueia o loop principal.
    """
    from threading import Thread

    def loop():
        HORARIOS_UTC = {8, 20}   # horas UTC para rodar settlement
        ultimo_dia  = None
        ultima_hora = None

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

            time.sleep(60)  # checar a cada minuto

    Thread(target=loop, daemon=True).start()


# FIX: listener de comandos Telegram iniciado aqui.
# Sem isso, /status /settlement /help nunca funcionam.
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

            # Recarrega bankroll a cada cidade
            bankroll = load_bankroll()
            balance  = bankroll["balance"]
            history  = bankroll["history"]

            current_exposure = open_exposure(history)
            # MAX_TOTAL_EXPOSURE agora é valor fixo em USD ($40), não fração
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

                # ── Filtro de sobreposição: 1 trade por evento por ciclo ──────
                # Guarda o outcome de maior EV por event_slug.
                # Evita entrar em 27°C e 28°C do mesmo evento (Milan D+1).
                # BUG CORRIGIDO: antes era populado como lista na pré-passagem,
                # então isinstance(prev_best, tuple) nunca era True e o filtro
                # nunca disparava — todos os outcomes com edge entravam.
                # Agora começa vazio e é preenchido como tupla no loop abaixo.
                best_ev_per_event: dict = {}   # event_slug → (ev, market_id)

                for market in markets:

                    try:
                        market_price = float(
                            market.get("yes_price", market.get("price", 0))
                        )

                        # Filtros de preço básico (saudabilidade do mercado)
                        if market_price < MIN_MARKET_PRICE:
                            continue
                        if market_price > MAX_MARKET_PRICE:
                            continue

                        # Filtro de liquidez: mercados muito baratos/caros têm
                        # spread bid/ask enorme — o EV calculado é ilusório.
                        # Ex: Toronto 17°C a $0.055 → EV +943% irreal.
                        if market_price < MIN_LIQUIDITY_PRICE:
                            print(f"  ⚠️  Liquidez insuficiente (price={market_price:.3f} < {MIN_LIQUIDITY_PRICE}). Pulando.")
                            continue
                        if market_price > MAX_LIQUIDITY_PRICE:
                            print(f"  ⚠️  Liquidez insuficiente (price={market_price:.3f} > {MAX_LIQUIDITY_PRICE}). Pulando.")
                            continue

                        market_id   = market.get("market_id")
                        condition   = market.get("condition", "ABOVE").upper()
                        unit        = market.get("unit", "C")
                        target      = float(market.get("target", 0))
                        target_high = market.get("target_high")
                        if target_high is not None:
                            target_high = float(target_high)

                        # ── Filtro D1+ — só entra para amanhã+ ──────────────
                        try:
                            market_date_obj = datetime.strptime(
                                market.get("market_date", ""), "%Y-%m-%d"
                            ).date()
                            today_date = utcnow().date()

                            if market_date_obj <= today_date:
                                print(
                                    f"  ⏭️  Pulando {market.get('question', '')[:40]} "
                                    f"({market.get('market_date')} ≤ {today_date})"
                                )
                                continue
                        except Exception as e:
                            print(f"  ⚠️  Erro ao processar data: {e}")
                            continue

                        # Anti-duplicata
                        if already_traded(history, market_id):
                            continue

                        # Capacidade de exposição restante
                        current_exposure   = open_exposure(history)
                        remaining_capacity = max_allowed - current_exposure

                        if remaining_capacity <= 0:
                            print(f"  Capacidade esgotada para {city}.")
                            break

                        # Horizonte de forecast
                        try:
                            mdate        = datetime.strptime(
                                market.get("market_date", ""), "%Y-%m-%d"
                            ).date()
                            today        = utcnow().date()
                            forecast_day = max(0, min((mdate - today).days, 3))
                        except Exception:
                            forecast_day = 1

                        # ── Modelo probabilístico ────────────────────────────
                        # FIX: passando target, unit e condition corretamente.
                        # Antes: market_date e question eram passados como kwargs
                        # inexistentes → target ficava 0, model calculava
                        # P(temp > 0°C) ≈ 100% — edge completamente falso.
                        try:
                            model_prob = calculate_probability(
                                city=city,
                                target=target,
                                unit=unit,
                                forecast_day=forecast_day,
                                condition=condition.lower(),  # 'above','below','exact','range'
                                target_high=target_high,      # só relevante para 'range'
                            )
                        except Exception as e:
                            print(f"  ⚠️  Erro no modelo: {e}")
                            continue

                        if not model_prob or model_prob <= 0 or model_prob >= 1:
                            continue

                        edge = round(model_prob - market_price, 4)
                        ev   = expected_value(model_prob, market_price)

                        print(
                            f"  {market.get('question', '')[:60]} | "
                            f"Model:{model_prob:.3f} Mkt:{market_price:.3f} "
                            f"Edge:{edge:+.3f} EV:{ev:+.3f} [{unit}]"
                        )

                        if edge < EDGE_THRESHOLD:
                            continue

                        # Rejeita EVs impossíveis — sinal de mercado ilíquido
                        # ou bug no modelo. EV > MAX_EV não é alfa real.
                        if ev > MAX_EV:
                            print(f"  🚫 EV={ev:+.3f} acima do cap ({MAX_EV}). "
                                  f"Provável modelo mal calibrado. Pulando.")
                            continue

                        # ── Filtro de sobreposição por evento ────────────────
                        # Só o outcome de maior EV por evento entra no ciclo.
                        # Evita apostas em 27°C e 28°C do mesmo evento (risco duplicado).
                        event_slug = market.get("event_slug", market.get("market_date", ""))
                        prev_best  = best_ev_per_event.get(event_slug)
                        if isinstance(prev_best, tuple):
                            prev_ev, prev_id = prev_best
                            if ev <= prev_ev:
                                print(f"  ⏩ Sobreposição: EV={ev:+.3f} < melhor do evento ({prev_ev:+.3f}). Pulando.")
                                continue
                            else:
                                # Este é melhor — o anterior será ignorado (já não executa mais)
                                print(f"  🔄 Novo melhor EV para o evento: {ev:+.3f} > {prev_ev:+.3f}")
                        # Registra este como melhor até agora para o evento
                        best_ev_per_event[event_slug] = (ev, market.get("market_id"))

                        print("  → EDGE POSITIVO — calculando stake Kelly")

                        stake = kelly_stake(balance, model_prob, market_price)

                        if stake <= 0:
                            continue

                        # Cap pela capacidade de exposição restante
                        stake = min(stake, remaining_capacity)

                        # Garantir máximo de $5
                        if stake > MAX_POSITION_DOLARES:
                            stake = MAX_POSITION_DOLARES

                        # FIX: dimensionamento correto — calcular shares inteiros
                        # a partir do stake em USD, depois derivar custo real.
                        # Evita acúmulo de erro de arredondamento em preços baixos.
                        shares    = int(stake / market_price)
                        if shares <= 0:
                            continue
                        real_cost = round(shares * market_price, 2)
                        stake     = real_cost  # custo efetivo, não estimado

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
                            "target_high":  target_high,  # None exceto em 'range'
                            "shares":       shares,          # novo campo
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

                        # Registrar previsão no sistema de validação
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

                        msg = (
                            f"[TRADE] {city_display.upper()} | {condition}\n"
                            f"Q: {market.get('question', '')}\n"
                            f"Model: {model_prob:.3f} | Market: {market_price:.3f}\n"
                            f"Edge: {edge:+.3f} | EV: {ev:+.3f} | Unit: {unit}\n"
                            f"Target: {target} | Shares: {shares} | "
                            f"Stake: ${stake:.2f} | Saldo: ${balance:.2f}"
                        )
                        print(f"  >>> TRADE EXECUTADO\n{msg}")

                        # 📱 Notificar Telegram
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
                        print(f"  Erro market: {e}")
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
