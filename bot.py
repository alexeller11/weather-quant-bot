#!/usr/bin/env python3
"""
Weather Quant Bot v3 - Loop principal com consenso, calibração e ML.
Integração revisada – pronto para uso.
"""

import logging
import time
import schedule
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# ============================================================
# Ajuste aqui os nomes das classes se forem diferentes no seu código
# ============================================================
try:
    from gamma_parser import GammaParser       # sua classe original
except ImportError:
    from gamma_parser import GammaAPI as GammaParser  # fallback

try:
    from forecast import ForecastProvider
except ImportError:
    from forecast import OpenMeteoForecast as ForecastProvider

from model import WeatherModel
from risk import RiskManager
from bankroll import Bankroll
from settlement import SettlementEngine
from notificador import Notificador

from consensus import ConsensusEngine

from config import TRADING_ENABLED, MAX_OPEN_TRADES, MAX_TOTAL_EXPOSURE, CITIES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("bot")


class WeatherQuantBot:
    def __init__(self):
        self.gamma = GammaParser()
        self.forecast_provider = ForecastProvider()
        self.model = WeatherModel()
        self.risk = RiskManager()
        self.bankroll = Bankroll()
        self.settlement_engine = SettlementEngine()
        self.notificador = Notificador()
        self.consensus_engine = ConsensusEngine()   # chave WEATHERAPI_KEY do ambiente
        self.open_trades: List[Dict] = []

    def fetch_markets(self, city: Dict) -> List[Dict]:
        return self.gamma.get_markets(city)

    def process_city(self, city: Dict):
        logger.info(f"Processando: {city['name']}")
        markets = self.fetch_markets(city)
        if not markets:
            return

        for market in markets:
            forecast_temp = self.forecast_provider.get_forecast(city, market['date'])
            if forecast_temp is None:
                continue

            # Consenso multi-fonte
            consensus = self.consensus_engine.consensus_temperature(
                lat=city['lat'],
                lon=city['lon'],
                date_str=market['date'].strftime('%Y-%m-%d'),
                temp_openmeteo=forecast_temp,
                threshold=3.0
            )
            if not consensus['consensus']:
                logger.info(f"🚫 Consenso bloqueou {city['name']}: {consensus['reason']}")
                continue

            # Modelo probabilístico (já com sigma calibrado e ajuste ML)
            model_prob = self.model.calculate_probability(
                city=city['name'],
                target_temp=market['target_temp'],
                forecast_temp=forecast_temp,
                day_offset=market['day_offset']
            )

            edge = model_prob - market['price']
            if edge <= 0:
                continue

            if not self.risk.check_guardrails(market, model_prob, forecast_temp):
                continue

            stake = self.risk.kelly_stake(model_prob, market['price'])
            if stake <= 0:
                continue

            if TRADING_ENABLED:
                trade = {
                    "id": f"{market['id']}_{int(time.time())}",
                    "city": city['name'],
                    "lat": city['lat'],          # NOVO: necessário para liquidação real
                    "lon": city['lon'],          # NOVO
                    "condition": market['condition'],
                    "target_temp": market['target_temp'],
                    "forecast_temp": forecast_temp,
                    "model_prob": model_prob,
                    "price": market['price'],
                    "stake": stake,
                    "date": market['date'].strftime('%Y-%m-%d'),
                    "day_offset": market['day_offset'],
                    "status": "OPEN",
                    "timestamp": datetime.now().isoformat()
                }
                self.open_trades.append(trade)
                self.bankroll.record_trade(trade)
                self.notificador.notify_trade(trade, edge, consensus)
                self.bankroll.update_exposure(trade)
            else:
                logger.info(f"Sinal paper: {city['name']} {market['condition']} prob={model_prob:.3f} edge={edge:.3f}")

    def settlement_cycle(self):
        logger.info("Liquidação periódica...")
        self.settlement_engine.settle_open_trades(self.open_trades)
        self.bankroll.sync()

    def run(self):
        schedule.every(1).hours.do(self.scheduled_trading)
        schedule.every(1).hours.do(self.settlement_cycle)
        logger.info("Bot Weather Quant v3 iniciado.")
        while True:
            schedule.run_pending()
            time.sleep(30)

    def scheduled_trading(self):
        logger.info("=== Ciclo de trading ===")
        for city in CITIES:
            try:
                self.process_city(city)
            except Exception as e:
                logger.error(f"Erro em {city['name']}: {e}", exc_info=True)


if __name__ == "__main__":
    bot = WeatherQuantBot()
    bot.run()