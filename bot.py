#!/usr/bin/env python3
"""
Weather Quant Bot v3 - Loop principal com consenso, calibração e ML.
Totalmente adaptado à estrutura real do projeto.
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
# Importações reais baseadas na estrutura do projeto
# ============================================================

# gamma_parser.py - funções, não classe
import gamma_parser

# forecast.py - classe ForecastService
from forecast import ForecastService

# model.py - classe WeatherModel (com calibração e ML)
from model import WeatherModel

# risk.py - funções
from risk import kelly_criterion, check_guardrails

# bankroll.py - funções
from bankroll import load_bankroll, save_trade, get_open_trades, update_trade

# settlement.py - classe SettlementEngine
from settlement import SettlementEngine

# notificador.py - funções
from notificador import notify_trade

# NOVO: motor de consenso
from consensus import ConsensusEngine

# Configurações
try:
    from config import (
        TRADING_ENABLED, MAX_OPEN_TRADES, MAX_TOTAL_EXPOSURE,
        MIN_PROB_ABOVE_BELOW, MIN_TARGET_ZSCORE, CITIES,
        MAX_POSITION, KELLY_FRACTION
    )
except ImportError as e:
    logger.error(f"Erro ao importar config: {e}")
    sys.exit(1)

# ============================================================
# Inicialização
# ============================================================

def load_cities():
    """Carrega a lista de cidades."""
    if CITIES:
        logger.info(f"Cidades carregadas do config: {len(CITIES)}")
        return CITIES
    
    # Fallback para cities.json
    cities_path = os.path.join(os.path.dirname(__file__), 'cities.json')
    try:
        with open(cities_path, 'r') as f:
            cities = json.load(f)
        logger.info(f"Cidades carregadas do JSON: {len(cities)}")
        return cities
    except FileNotFoundError:
        logger.error(f"Arquivo {cities_path} não encontrado!")
        return []
    except Exception as e:
        logger.error(f"Erro ao carregar cidades: {e}")
        return []

# Instâncias globais
forecast_service = ForecastService()
model = WeatherModel()
settlement_engine = SettlementEngine()
consensus_engine = ConsensusEngine()
cities = load_cities()
open_trades = []

# ============================================================
# Funções principais
# ============================================================

def fetch_markets(city: Dict) -> List[Dict]:
    """Obtém mercados ativos para uma cidade via Gamma API."""
    try:
        return gamma_parser.get_markets(city)
    except Exception as e:
        logger.error(f"Erro ao buscar mercados para {city.get('name', 'unknown')}: {e}")
        return []

def process_city(city: Dict):
    """Processa uma cidade: coleta, avalia e opcionalmente executa trades."""
    logger.info(f"Processando cidade: {city['name']}")

    markets = fetch_markets(city)
    if not markets:
        logger.info(f"Nenhum mercado ativo para {city['name']}")
        return

    for market in markets:
        try:
            # 1. Previsão de temperatura
            forecast_temp = forecast_service.get_forecast(city, market['date'])
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

            if not check_guardrails(market, model_prob, forecast_temp):
                continue

            # 5. Dimensionamento via Kelly
            stake = kelly_criterion(model_prob, market['price'])
            if stake <= 0:
                continue

            # 6. Execução paper
            if TRADING_ENABLED:
                trade = execute_trade(market, stake, model_prob, forecast_temp, city)
                if trade:
                    open_trades.append(trade)
                    try:
                        notify_trade(trade, edge, consensus)
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
    # Verificar limites de exposição
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
        save_trade(trade)
    except Exception as e:
        logger.error(f"Erro ao salvar trade: {e}")
    
    logger.info(f"Trade executado: {trade['id']}")
    return trade

def settlement_cycle():
    """Executa liquidação de trades abertos periodicamente."""
    global open_trades
    logger.info("Iniciando ciclo de liquidação...")
    try:
        # Usa o método settle_all da classe SettlementEngine
        settlement_engine.settle_all()
        # Recarrega trades abertos
        open_trades = get_open_trades()
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

# ============================================================
# Ponto de entrada
# ============================================================

if __name__ == "__main__":
    run()