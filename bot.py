#!/usr/bin/env python3
"""
Weather Quant Bot v3 - Paper trading real na Polymarket.
"""

import logging, time, json, os, sys, schedule
from datetime import datetime
from typing import Dict, List, Optional

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("bot")

# ============================================================
# Importações — verificadas contra as APIs reais exportadas
# ============================================================
from gamma_parser import fetch_markets
from forecast import get_forecast, get_corrected_forecast
from model import calculate_probability
from risk import kelly_criterion, check_guardrails

# FIX: bankroll não exporta _save_to_db, get_open_trades nem update_trade.
# Usar save_bankroll / load_bankroll / already_traded que são a API pública.
from bankroll import load_bankroll, save_bankroll, already_traded

from settlement import settle_all
from notificador import notificar_entrada_trade
from consensus import ConsensusEngine

from config import (TRADING_ENABLED, MAX_OPEN_TRADES, MAX_TOTAL_EXPOSURE,
                    MAX_POSITION, CITIES)

# ============================================================
consensus_engine = ConsensusEngine()
cities = CITIES

if not cities:
    logger.error("Nenhuma cidade disponível.")
    sys.exit(1)

logger.info(f"🤖 {len(cities)} cidades | Trading: {'ON' if TRADING_ENABLED else 'OFF (observação)'}")


def _get_open_trades(history):
    """Retorna trades com resultado OPEN da lista de histórico."""
    return [t for t in history if t.get("result") == "OPEN"]


def process_city(city: Dict):
    name = city["name"]
    logger.info(f"📍 {name}")

    try:
        markets = fetch_markets(name)
    except Exception as e:
        logger.error(f"❌ fetch_markets({name}): {e}")
        return

    if not markets:
        logger.debug(f"📭 {name}: sem mercados")
        return

    logger.info(f"📋 {name}: {len(markets)} mercados")

    # Carrega bankroll uma vez por cidade para evitar race conditions
    data = load_bankroll()
    history = data.get("history", [])
    balance = float(data.get("balance", 0))

    for m in markets:
        try:
            market_date = m.get("market_date", "")
            market_id   = str(m.get("market_id", ""))

            # Ignora mercado já negociado
            if already_traded(history, market_id):
                logger.debug(f"  Já negociado: {market_id}")
                continue

            # Verifica limite de trades abertos
            open_count = len(_get_open_trades(history))
            if open_count >= MAX_OPEN_TRADES:
                logger.info(f"🛑 Limite de {MAX_OPEN_TRADES} trades abertos atingido")
                break

            # Verifica exposição total
            exposure = sum(float(t.get("stake", 0)) for t in _get_open_trades(history))
            if exposure >= MAX_TOTAL_EXPOSURE:
                logger.info(f"🛑 Exposição máxima ${MAX_TOTAL_EXPOSURE:.2f} atingida")
                break

            # FIX: get_forecast retorna (forecast_c, sigma) — desempacotar antes de usar.
            # O bot anterior passava a tupla inteira como forecast_temp para calculate_probability.
            forecast_result = get_forecast(name.lower().replace(" ", "-"), 1)
            if forecast_result is None or forecast_result[0] is None:
                logger.debug(f"  Forecast indisponível para {name}")
                continue

            forecast_c, sigma = forecast_result  # desempacotar corretamente

            date_str = market_date if isinstance(market_date, str) else str(market_date)

            # Consenso entre fontes
            cons = consensus_engine.consensus_temperature(
                city["lat"], city["lon"], date_str, forecast_c
            )
            if not cons["consensus"]:
                logger.info(f"🚫 {name}: {cons['reason']}")
                continue

            condition  = m.get("condition", "above").upper()
            target     = float(m.get("target", 0))
            unit       = m.get("unit", "C")
            yes_price  = float(m.get("yes_price", 0))

            # FIX: calculate_probability(city, target_temp, forecast_temp, day_offset)
            # forecast_temp deve ser float, não tupla.
            day_offset = 1
            try:
                from datetime import date as _date
                mdate = datetime.strptime(date_str, "%Y-%m-%d").date()
                day_offset = max(1, (mdate - datetime.utcnow().date()).days)
            except Exception:
                pass

            prob = calculate_probability(name, target, forecast_c, day_offset)
            edge = prob - yes_price

            if edge <= 0:
                continue

            # Guardrails
            market_dict = {
                "condition":   condition,
                "target_temp": target,
                "price":       yes_price,
                "day_offset":  day_offset,
            }
            if not check_guardrails(market_dict, prob, forecast_c):
                continue

            stake = min(kelly_criterion(prob, yes_price), MAX_POSITION)
            if stake <= 0:
                continue

            shares    = int(stake / yes_price) if yes_price > 0 else 0
            real_cost = round(shares * yes_price, 2)
            stake     = real_cost

            if stake <= 0:
                continue

            trade = dict(
                market_id    = market_id,
                city         = name,
                question     = m.get("question", ""),
                market_date  = date_str,
                entry_time   = datetime.utcnow().isoformat(),
                exit_time    = None,
                type         = condition,
                unit         = unit,
                target       = target,
                forecast_c   = forecast_c,
                sigma_total  = round(sigma, 4),
                shares       = shares,
                model_prob   = round(prob, 4),
                market_price = yes_price,
                edge         = round(edge, 4),
                ev           = round(prob / yes_price - 1, 4) if yes_price > 0 else 0,
                stake        = stake,
                result       = "OPEN",
                pnl          = 0,
                fee          = 0.0,
                forecast_day = day_offset,
                real_temp_c  = None,
            )

            if TRADING_ENABLED:
                history.append(trade)
                balance -= stake
                data["history"] = history
                data["balance"]  = round(balance, 4)
                save_bankroll(data)
                logger.info(
                    f"✅ TRADE: {name} {condition} {target}°{unit} | "
                    f"prob={prob:.3f} edge={edge:.3f} stake=${stake:.2f}"
                )
                try:
                    notificar_entrada_trade(
                        city=name, market_date=date_str, target=target,
                        unit=unit, stake=stake, model_prob=prob,
                        market_price=yes_price, edge=edge,
                        balance=balance, shares=shares,
                    )
                except Exception:
                    pass
            else:
                logger.info(
                    f"📊 SINAL: {name} {condition} {target}°{unit} | "
                    f"prob={prob:.3f} edge={edge:.3f} stake=${stake:.2f}"
                )

        except Exception as e:
            logger.error(f"❌ {name} mercado {m.get('market_id','?')}: {e}", exc_info=True)


def settlement_cycle():
    logger.info("🔄 Liquidação...")
    try:
        settle_all()
    except Exception as e:
        logger.error(f"❌ Liquidação: {e}", exc_info=True)


def scheduled_trading():
    logger.info(f"🚀 CICLO {datetime.now():%H:%M:%S}")
    for city in cities:
        try:
            process_city(city)
        except Exception as e:
            logger.error(f"❌ {city.get('name','?')}: {e}", exc_info=True)
    logger.info("✅ FIM CICLO")


def run():
    schedule.every(1).hours.do(scheduled_trading)
    schedule.every(1).hours.do(settlement_cycle)
    scheduled_trading()
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    logger.info("🌤️ WEATHER QUANT BOT v3")
    run()
