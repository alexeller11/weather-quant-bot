#!/usr/bin/env python3
"""
Weather Quant Bot v3 - Loop principal com consenso, calibração e ML.
"""

import logging
import time
import json
import os
import sys
import schedule
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("bot")

# Importações
import gamma_parser
import forecast
import model
import risk
import bankroll
import settlement
import notificador
from consensus import ConsensusEngine

# Configurações - AGORA USA CITIES DIRETAMENTE
try:
    from config import (
        TRADING_ENABLED, MAX_OPEN_TRADES, MAX_TOTAL_EXPOSURE,
        MIN_PROB_ABOVE_BELOW, MIN_TARGET_ZSCORE, MAX_POSITION,
        KELLY_FRACTION, CITIES
    )
except ImportError:
    TRADING_ENABLED = 0
    MAX_OPEN_TRADES = 4
    MAX_TOTAL_EXPOSURE = 8.0
    MIN_PROB_ABOVE_BELOW = 0.70
    MIN_TARGET_ZSCORE = 1.50
    MAX_POSITION = 2.00
    KELLY_FRACTION = 0.50
    CITIES = []

# Estado global
consensus_engine = ConsensusEngine()
cities = CITIES  # USA DIRETO DO CONFIG
open_trades = []

if not cities:
    logger.error("Nenhuma cidade disponível. Bot não pode operar.")
    sys.exit(1)

logger.info(f"Bot iniciado com {len(cities)} cidades.")

# ============================================================
# Funções principais (mantidas iguais)
# ============================================================

def process_city(city: Dict):
    logger.info(f"Processando cidade: {city['name']}")
    try:
        markets = gamma_parser.get_markets(city['name'])
    except Exception as e:
        logger.error(f"Erro ao buscar mercados para {city['name']}: {e}")
        return

    if not markets:
        logger.info(f"Nenhum mercado ativo para {city['name']}")
        return

    for market in markets:
        try:
            forecast_temp = forecast.get_forecast(city, market['date'])
            if forecast_temp is None:
                continue

            consensus = consensus_engine.consensus_temperature(
                lat=city['lat'], lon=city['lon'],
                date_str=market['date'].strftime('%Y-%m-%d'),
                temp_openmeteo=forecast_temp, threshold=3.0
            )
            if not consensus['consensus']:
                logger.info(f"🚫 Consenso bloqueou {city['name']} {market['condition']}")
                continue

            model_prob = model.calculate_probability(
                city=city['name'],
                target_temp=market['target_temp'],
                forecast_temp=forecast_temp,
                day_offset=market['day_offset']
            )

            edge = model_prob - market['price']
            if edge <= 0:
                continue
            if not risk.check_guardrails(market, model_prob, forecast_temp):
                continue

            stake = risk.kelly_criterion(model_prob, market['price'])
            if stake <= 0:
                continue

            if TRADING_ENABLED:
                trade = {
                    "id": f"{market.get('id', 'unknown')}_{int(time.time())}",
                    "city": city['name'],
                    "lat": city['lat'],
                    "lon": city['lon'],
                    "condition": market['condition'],
                    "target_temp": market['target_temp'],
                    "forecast_temp": forecast_temp,
                    "model_prob": model_prob,
                    "price": market['price'],
                    "stake": stake,
                    "date": market['date'].strftime('%Y-%m-%d') if isinstance(market['date'], datetime) else str(market['date']),
                    "day_offset": market['day_offset'],
                    "status": "OPEN",
                    "timestamp": datetime.now().isoformat()
                }
                try:
                    bankroll.save_trade(trade)
                    open_trades.append(trade)
                    try:
                        notificador.notify_trade(trade, edge, consensus)
                    except Exception:
                        pass
                    logger.info(f"Trade executado: {trade['id']}")
                except Exception as e:
                    logger.error(f"Erro ao salvar trade: {e}")
            else:
                logger.info(f"Sinal: {city['name']} {market['condition']} prob={model_prob:.3f} edge={edge:.3f}")
        except Exception as e:
            logger.error(f"Erro processando mercado: {e}", exc_info=True)

def settlement_cycle():
    global open_trades
    logger.info("Iniciando ciclo de liquidação...")
    try:
        settlement.settle_all()
        open_trades = bankroll.get_open_trades()
    except Exception as e:
        logger.error(f"Erro na liquidação: {e}", exc_info=True)

def scheduled_trading():
    logger.info("=== Ciclo de trading ===")
    for city in cities:
        try:
            process_city(city)
        except Exception as e:
            logger.error(f"Erro em {city.get('name', 'unknown')}: {e}", exc_info=True)

def run():
    schedule.every(1).hours.do(scheduled_trading)
    schedule.every(1).hours.do(settlement_cycle)
    logger.info(f"Bot iniciado com {len(cities)} cidades. Aguardando primeiro ciclo...")
    while True:
        schedule.run_pending()
        time.sleep(30)

if __name__ == "__main__":
    run()