#!/usr/bin/env python3
"""
Weather Quant Bot v3 - Loop principal com consenso, calibração e ML.
Estrutura totalmente compatível com o projeto original (baseado em funções).
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
# Importações REAIS - todas verificadas no GitHub
# ============================================================

# gamma_parser: função get_markets(city_name)
import gamma_parser

# forecast: função get_forecast(city, target_date)
import forecast

# model: funções calculate_probability(), get_calibrator(), get_ml_adjuster()
import model

# risk: funções kelly_criterion(), check_guardrails()
import risk

# bankroll: funções load_bankroll(), save_trade(), get_open_trades(), update_trade()
import bankroll

# settlement: funções settle_all(), settle_trade()
import settlement

# notificador: funções notify_trade()
import notificador

# NOVO: motor de consenso
from consensus import ConsensusEngine

# Configurações
try:
    from config import (
        TRADING_ENABLED, MAX_OPEN_TRADES, MAX_TOTAL_EXPOSURE,
        MIN_PROB_ABOVE_BELOW, MIN_TARGET_ZSCORE, MAX_POSITION,
        KELLY_FRACTION
    )
except ImportError as e:
    logger.error(f"Erro ao importar config: {e}")
    # Valores padrão para não quebrar
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

# ============================================================
# Estado global
# ============================================================

consensus_engine = ConsensusEngine()
cities = load_cities()
open_trades = []

# ============================================================
# Funções principais
# ============================================================

def process_city(city: Dict):
    """Processa uma cidade: coleta, avalia e opcionalmente executa trades."""
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
            # 1. Previsão de temperatura
            forecast_temp = forecast.get_forecast(city, market['date'])
            if forecast_temp is None:
                logger.warning(f"Previsão indisponível para {city['name']} em {market['date']}")
                continue

            # 2. Consenso multi-fonte (NOVO)
            consensus = consensus_engine.consensus_temperature(
                lat=city['lat'],
                lon=city['lon'],
                date_str=market['date'].strftime('%Y-%m-%d'),
                temp_openmeteo=forecast_temp,
                threshold=3.0
            )
            if not consensus['consensus']:
                logger.info(
                    f"🚫 Consenso bloqueou {city['name']} {market['condition']}: "
                    f"{consensus['reason']}"
                )
                continue

            # 3. Modelagem probabilística (com sigma calibrado e ML)
            model_prob = model.calculate_probability(
                city=city['name'],
                target_temp=market['target_temp'],
                forecast_temp=forecast_temp,
                day_offset=market['day_offset']
            )

            # 4. Edge e guardrails
            edge = model_prob - market['price']
            if edge <= 0:
                continue

            if not risk.check_guardrails(market, model_prob, forecast_temp):
                continue

            # 5. Dimensionamento via Kelly
            stake = risk.kelly_criterion(model_prob, market['price'])
            if stake <= 0:
                continue

            # 6. Execução paper
            if TRADING_ENABLED:
                trade = execute_trade(market, stake, model_prob, forecast_temp, city)
                if trade:
                    open_trades.append(trade)
                    try:
                        notificador.notify_trade(trade, edge, consensus)
                    except Exception as e:
                        logger.warning(f"Erro ao enviar notificação: {e}")
            else:
                logger.info(
                    f"Paper trade sinalizado (não executado): "
                    f"{city['name']} {market['condition']} prob={model_prob:.3f} edge={edge:.3f}"
                )
        except Exception as e:
            logger.error(f"Erro processando mercado: {e}", exc_info=True)
            continue

def execute_trade(market: Dict, stake: float, model_prob: float, forecast_temp: float, city: Dict) -> Optional[Dict]:
    """Cria o registro do trade e persiste."""
    if len(open_trades) >= MAX_OPEN_TRADES:
        logger.info("🚫 Número máximo de trades abertos atingido")
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
    """Executa liquidação de trades abertos periodicamente."""
    global open_trades
    logger.info("Iniciando ciclo de liquidação...")
    try:
        settlement.settle_all()
        open_trades = bankroll.get_open_trades()
    except Exception as e:
        logger.error(f"Erro no ciclo de liquidação: {e}", exc_info=True)

def scheduled_trading():
    """Ciclo de trading para todas as cidades."""
    logger.info("=== Ciclo de trading ===")
    for city in cities:
        try:
            process_city(city)
        except Exception as e:
            logger.error(f"Erro processando {city.get('name', 'unknown')}: {e}", exc_info=True)

def run():
    """Loop principal agendado."""
    schedule.every(1).hours.do(scheduled_trading)
    schedule.every(1).hours.do(settlement_cycle)

    logger.info(f"Bot iniciado com {len(cities)} cidades. Aguardando primeiro ciclo...")
    while True:
        schedule.run_pending()
        time.sleep(30)

if __name__ == "__main__":
    run()