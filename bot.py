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
# Importações REAIS - todas verificadas agorinha
# ============================================================
import gamma_parser                # funções soltas
import forecast                    # funções soltas
from model import calculate_probability, get_calibrator, get_ml_adjuster
from risk import kelly_criterion, check_guardrails
from bankroll import save_trade, get_open_trades
from settlement import settle_all
from notificador import notify_trade
from consensus import ConsensusEngine

from config import (TRADING_ENABLED, MAX_OPEN_TRADES, MAX_TOTAL_EXPOSURE,
                    MAX_POSITION, CITIES)

# ============================================================
consensus_engine = ConsensusEngine()
cities = CITIES
open_trades = []

if not cities:
    logger.error("Nenhuma cidade disponível.")
    sys.exit(1)

logger.info(f"🤖 {len(cities)} cidades | Paper: {bool(TRADING_ENABLED)}")

def process_city(city: Dict):
    name = city['name']
    logger.info(f"📍 {name}")

    try:
        markets = gamma_parser.fetch_markets(name)
    except Exception as e:
        logger.error(f"❌ fetch_markets({name}): {e}")
        return

    if not markets:
        logger.debug(f"📭 {name}: sem mercados")
        return

    logger.info(f"📋 {name}: {len(markets)} mercados")

    for m in markets:
        try:
            fc = forecast.get_forecast(city, m['date'])
            if fc is None: continue

            date_str = m['date'].strftime('%Y-%m-%d') if isinstance(m['date'], datetime) else str(m['date'])
            cons = consensus_engine.consensus_temperature(city['lat'], city['lon'], date_str, fc)
            if not cons['consensus']:
                logger.info(f"🚫 {name} {m['condition']}: {cons['reason']}")
                continue

            prob = calculate_probability(name, m['target_temp'], fc, m['day_offset'])
            edge = prob - m['price']
            if edge <= 0: continue
            if not check_guardrails(m, prob, fc): continue

            stake = min(kelly_criterion(prob, m['price']), MAX_POSITION)
            if stake <= 0: continue

            if TRADING_ENABLED:
                trade = dict(id=f"{m.get('id')}_{int(time.time())}", city=name,
                             lat=city['lat'], lon=city['lon'],
                             condition=m['condition'], target_temp=m['target_temp'],
                             forecast_temp=fc, model_prob=round(prob,4),
                             price=m['price'], stake=round(stake,2), edge=round(edge,4),
                             date=date_str, day_offset=m['day_offset'],
                             status="OPEN", timestamp=datetime.now().isoformat())
                save_trade(trade)
                open_trades.append(trade)
                logger.info(f"✅ TRADE: {name} {m['condition']} {m['target_temp']}°F | prob={prob:.3f} edge={edge:.3f} stake=${stake:.2f}")
                try: notify_trade(trade)
                except Exception: pass
            else:
                logger.info(f"📊 SINAL: {name} {m['condition']} {m['target_temp']}°F | prob={prob:.3f} edge={edge:.3f} stake=${stake:.2f}")
        except Exception as e:
            logger.error(f"❌ {name} mercado {m.get('id','?')}: {e}")

def settlement_cycle():
    logger.info("🔄 Liquidação...")
    try:
        settle_all()
        global open_trades
        open_trades = get_open_trades()
    except Exception as e:
        logger.error(f"❌ Liquidação: {e}")

def scheduled_trading():
    logger.info(f"🚀 CICLO {datetime.now():%H:%M:%S}")
    for city in cities:
        try: process_city(city)
        except Exception as e: logger.error(f"❌ {city.get('name','?')}: {e}")
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