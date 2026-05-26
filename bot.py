#!/usr/bin/env python3
"""
Weather Quant Bot v3 - Loop principal com consenso, calibração e ML.
Totalmente compatível com a estrutura real do projeto.
"""

import logging
import time
import json
import os
import sys
import schedule
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("bot")

# ============================================================
# Importações com fallback silencioso
# ============================================================

# gamma_parser - função get_markets
import gamma_parser

# forecast - função get_forecast
import forecast

# model - funções calculate_probability, get_calibrator, get_ml_adjuster
import model

# risk - funções kelly_criterion, check_guardrails
import risk

# bankroll - funções save_trade, get_open_trades, update_trade
import bankroll

# settlement - funções settle_all
import settlement

# notificador - funções notify_trade
import notificador

# NOVO: motor de consenso
from consensus import ConsensusEngine

# Configurações (importação segura)
try:
    from config import (
        TRADING_ENABLED, MAX_OPEN_TRADES, MAX_TOTAL_EXPOSURE,
        MIN_PROB_ABOVE_BELOW, MIN_TARGET_ZSCORE, MAX_POSITION,
        KELLY_FRACTION
    )
except ImportError:
    TRADING_ENABLED = 0
    MAX_OPEN_TRADES = 4
    MAX_TOTAL_EXPOSURE = 8.0
    MIN_PROB_ABOVE_BELOW = 0.70
    MIN_TARGET_ZSCORE = 1.50
    MAX_POSITION = 2.00
    KELLY_FRACTION = 0.50

# ============================================================
# Carregamento de cidades
# ============================================================

def load_cities():
    """Carrega a lista de cidades do arquivo cities.json"""
    cities_path = os.path.join(os.path.dirname(__file__), 'cities.json')
    try:
        with open(cities_path, 'r') as f:
            cities = json.load(f)
        logger.info(f"Cidades carregadas: {len(cities)}")
        return cities
    except FileNotFoundError:
        logger.error(f"Arquivo {cities_path} não encontrado!")
        return []
    except Exception as e:
        logger.error(f"Erro ao carregar cidades: {e}")
        return []

# Estado global
consensus_engine = ConsensusEngine()
cities = load_cities()
open_trades = []

# ============================================================
# Funções principais
# ============================================================

def process_city(city: Dict):
    """Processa uma cidade."""
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
            # Previsão
            forecast_temp = forecast.get_forecast(city, market['date'])
            if forecast_temp is None:
                continue

            # Consenso
            consensus = consensus_engine.consensus_temperature(
                lat=city['lat'], lon=city['lon'],
                date_str=market['date'].strftime('%Y-%m-%d'),
                temp_openmeteo=forecast_temp, threshold=3.0
            )
            if not consensus['consensus']:
                logger.info(f"🚫 Consenso bloqueou {city['name']} {market['condition']}")
                continue

            # Modelo
            model_prob = model.calculate_probability(
                city=city['name'],
                target_temp=market['target_temp'],
                forecast_temp=forecast_temp,
                day_offset=market['day_offset']
            )

            # Edge e guardrails
            edge = model_prob - market['price']
            if edge <= 0:
                continue
            if not risk.check_guardrails(market, model_prob, forecast_temp):
                continue

            # Kelly
            stake = risk.kelly_criterion(model_prob, market['price'])
            if stake <= 0:
                continue

            # Execução
            if TRADING_ENABLED:
                trade = execute_trade(market, stake, model_prob, forecast_temp, city)
                if trade:
                    open_trades.append(trade)
                    try:
                        notificador.notify_trade(trade, edge, consensus)
                    except Exception:
                        pass
            else:
                logger.info(f"Sinal: {city['name']} {market['condition']} prob={model_prob:.3f} edge={edge:.3f}")
        except Exception as e:
            logger.error(f"Erro processando mercado: {e}", exc_info=True)

def execute_trade(market: Dict, stake: float, model_prob: float, forecast_temp: float, city: Dict) -> Optional[Dict]:
    """Cria e persiste o trade."""
    if len(open_trades) >= MAX_OPEN_TRADES:
        logger.info("🚫 Máximo de trades abertos atingido")
        return None

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
    except Exception as e:
        logger.error(f"Erro ao salvar trade: {e}")
    
    logger.info(f"Trade executado: {trade['id']}")
    return trade

def settlement_cycle():
    """Liquidação periódica."""
    global open_trades
    logger.info("Iniciando ciclo de liquidação...")
    try:
        settlement.settle_all()
        open_trades = bankroll.get_open_trades()
    except Exception as e:
        logger.error(f"Erro na liquidação: {e}", exc_info=True)

def scheduled_trading():
    """Ciclo de trading para todas as cidades."""
    logger.info("=== Ciclo de trading ===")
    for city in cities:
        try:
            process_city(city)
        except Exception as e:
            logger.error(f"Erro em {city.get('name', 'unknown')}: {e}", exc_info=True)

def run():
    """Loop principal."""
    schedule.every(1).hours.do(scheduled_trading)
    schedule.every(1).hours.do(settlement_cycle)

    logger.info(f"Bot iniciado com {len(cities)} cidades.")
    while True:
        schedule.run_pending()
        time.sleep(30)

if __name__ == "__main__":
    run()