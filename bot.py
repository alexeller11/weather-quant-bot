#!/usr/bin/env python3
"""
Weather Quant Bot v3 - Loop principal com consenso, calibração e ML.
Integração revisada com base na análise real do repositório.
"""

import logging
import time
import json
import os
import schedule
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# Importações reais baseadas na análise dos arquivos
from gamma_parser import GammaParser
from forecast import ForecastProvider
from model import WeatherModel
from risk import RiskManager
from bankroll import Bankroll
from settlement import SettlementEngine
from notificador import Notificador
from consensus import ConsensusEngine
from config import (
    TRADING_ENABLED, MAX_OPEN_TRADES, MAX_TOTAL_EXPOSURE,
    MIN_PROB_ABOVE_BELOW, MIN_TARGET_ZSCORE
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("bot")

# Carrega cidades do arquivo JSON (solução para o problema 1)
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


class WeatherQuantBot:
    def __init__(self):
        self.gamma = GammaParser()
        self.forecast_provider = ForecastProvider()
        self.model = WeatherModel()
        self.risk = RiskManager()
        self.bankroll = Bankroll()
        self.settlement_engine = SettlementEngine()
        self.notificador = Notificador()
        self.consensus_engine = ConsensusEngine()  # chave WEATHERAPI_KEY do ambiente
        
        self.cities = load_cities()
        if not self.cities:
            logger.error("Nenhuma cidade carregada. Bot não pode operar.")
        
        self.last_run = None

    def fetch_markets(self, city: Dict) -> List[Dict]:
        """Obtém mercados ativos para uma cidade via Gamma API."""
        return self.gamma.get_markets(city)

    def process_city(self, city: Dict):
        """Processa uma cidade: coleta, avalia e opcionalmente executa trades."""
        logger.info(f"Processando cidade: {city['name']}")

        markets = self.fetch_markets(city)
        if not markets:
            logger.info(f"Nenhum mercado ativo para {city['name']}")
            return

        for market in markets:
            # 1. Previsão de temperatura
            forecast_temp = self.forecast_provider.get_forecast(city, market['date'])
            if forecast_temp is None:
                logger.warning(f"Previsão indisponível para {city['name']} em {market['date']}")
                continue

            # 2. Consenso multi-fonte (NOVO)
            consensus = self.consensus_engine.consensus_temperature(
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
            model_prob = self.model.calculate_probability(
                city=city['name'],
                target_temp=market['target_temp'],
                forecast_temp=forecast_temp,
                day_offset=market['day_offset']
            )

            # 4. Edge e guardrails
            edge = model_prob - market['price']
            if edge <= 0:
                continue

            if not self.risk.check_guardrails(market, model_prob, forecast_temp):
                continue

            # 5. Dimensionamento via Kelly
            stake = self.risk.kelly_stake(model_prob, market['price'])
            if stake <= 0:
                continue

            # 6. Execução paper
            if TRADING_ENABLED:
                trade = self.execute_trade(market, stake, model_prob, forecast_temp, city)
                if trade:
                    self.notificador.notify_trade(trade, edge, consensus)
            else:
                logger.info(
                    f"Paper trade sinalizado (não executado): "
                    f"{city['name']} {market['condition']} prob={model_prob:.3f} edge={edge:.3f}"
                )

    def execute_trade(self, market: Dict, stake: float, model_prob: float, forecast_temp: float, city: Dict) -> Optional[Dict]:
        """Cria o registro do trade e persiste."""
        # Verificar limites de exposição
        if not self.risk.check_exposure_limits(self.bankroll):
            logger.info("🚫 Limite de exposição atingido")
            return None

        trade = {
            "id": f"{market['id']}_{int(time.time())}",
            "city": city['name'],
            "lat": city['lat'],          # NOVO: necessário para liquidação
            "lon": city['lon'],          # NOVO: necessário para liquidação
            "condition": market['condition'],
            "target_temp": market['target_temp'],
            "forecast_temp": forecast_temp,
            "model_prob": model_prob,
            "price": market['price'],
            "stake": stake,
            "date": market['date'].strftime('%Y-%m-%d') if isinstance(market['date'], datetime) else market['date'],
            "day_offset": market['day_offset'],
            "status": "OPEN",
            "timestamp": datetime.now().isoformat()
        }
        
        self.bankroll.record_trade(trade)
        logger.info(f"Trade executado: {trade['id']}")
        return trade

    def settlement_cycle(self):
        """Executa liquidação de trades abertos periodicamente."""
        logger.info("Iniciando ciclo de liquidação...")
        try:
            # Usa o método original do settlement.py (settle_all)
            self.settlement_engine.settle_all()
            self.bankroll.sync()
        except Exception as e:
            logger.error(f"Erro no ciclo de liquidação: {e}", exc_info=True)

    def run(self):
        """Loop principal agendado."""
        schedule.every(1).hours.do(self.scheduled_trading)
        schedule.every(1).hours.do(self.settlement_cycle)

        logger.info(f"Bot iniciado com {len(self.cities)} cidades. Aguardando primeiro ciclo...")
        while True:
            schedule.run_pending()
            time.sleep(30)

    def scheduled_trading(self):
        """Ciclo de trading para todas as cidades."""
        logger.info("=== Ciclo de trading ===")
        for city in self.cities:
            try:
                self.process_city(city)
            except Exception as e:
                logger.error(f"Erro processando {city['name']}: {e}", exc_info=True)
        self.last_run = datetime.now()


if __name__ == "__main__":
    bot = WeatherQuantBot()
    bot.run()