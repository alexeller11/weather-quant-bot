#!/usr/bin/env python3
"""
Settlement Engine - Liquidação de trades com base em resultados reais.
Atualiza calibrador de sigma e modelo ML.
Integrado ao método settle_all original.
"""

import logging
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# NOVO: integração com módulos de calibração e ML
from sigma_calibrator import SigmaCalibrator
from ml_adjuster import MLProbabilityAdjuster
from model import get_calibrator, get_ml_adjuster
from bankroll import Bankroll

logger = logging.getLogger("settlement")

# Instâncias (reutiliza as globais do model.py)
_calibrator = get_calibrator()
_ml_adjuster = get_ml_adjuster()


class SettlementEngine:
    """Resolve trades abertos usando dados observados."""

    def __init__(self):
        self.bankroll = Bankroll()

    def get_actual_temperature(self, lat: float, lon: float, date: str) -> Optional[float]:
        """
        Consulta a temperatura máxima real na Open-Meteo Archive API.
        """
        try:
            url = "https://archive-api.open-meteo.com/v1/archive"
            params = {
                "latitude": lat,
                "longitude": lon,
                "start_date": date,
                "end_date": date,
                "daily": "temperature_2m_max",
                "timezone": "auto"
            }
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            temp = data['daily']['temperature_2m_max'][0]
            if temp is None:
                raise ValueError("Temperatura ausente na resposta")
            return float(temp)
        except Exception as e:
            logger.error(f"Falha ao obter temperatura real para ({lat},{lon}) em {date}: {e}")
            return None

    def settle_trade(self, trade: Dict) -> Dict:
        """
        Liquida um trade individual, atualiza calibração e ML.
        Retorna o trade com status atualizado.
        """
        # Verificar se já está liquidado
        if trade.get('status') != 'OPEN':
            return trade

        city = trade['city']
        date = trade['date']
        forecast_temp = trade['forecast_temp']
        model_prob = trade.get('model_prob', 0.5)  # fallback se não existir
        day_offset = trade.get('day_offset', 1)
        lat = trade.get('lat')
        lon = trade.get('lon')

        # Se não tiver coordenadas no trade, tenta buscar do cities.json
        if lat is None or lon is None:
            logger.warning(f"Trade {trade['id']} sem coordenadas. Tentando buscar...")
            lat, lon = self._get_city_coordinates(city)
            if lat is None:
                logger.error(f"Não foi possível obter coordenadas para {city}")
                return trade

        # 1. Obter temperatura real
        actual_temp = self.get_actual_temperature(lat, lon, date)
        if actual_temp is None:
            logger.warning(f"Temperatura real não disponível para {city} em {date}. Trade permanece OPEN.")
            return trade

        # 2. Determinar resultado
        condition = trade['condition']
        target_temp = trade['target_temp']
        if condition == 'ABOVE':
            won = actual_temp > target_temp
        elif condition == 'BELOW':
            won = actual_temp < target_temp
        else:  # EXACT
            won = abs(actual_temp - target_temp) <= 0.5

        trade['status'] = 'WON' if won else 'LOST'
        trade['actual_temp'] = actual_temp
        trade['settled_at'] = datetime.now().isoformat()

        # 3. Registrar no calibrador de sigma (NOVO)
        _calibrator.record_trade_result(
            city=city,
            day_offset=day_offset,
            predicted_temp=forecast_temp,
            actual_temp=actual_temp
        )

        # 4. Atualizar modelo ML (NOVO)
        _ml_adjuster.update(
            model_prob=model_prob,
            day_offset=day_offset,
            city=city,
            calibrator=_calibrator,
            trade_success=won
        )

        logger.info(
            f"Trade {trade['id']} liquidado: {trade['status']} "
            f"(forecast={forecast_temp}, actual={actual_temp})"
        )
        return trade

    def _get_city_coordinates(self, city_name: str) -> tuple:
        """Busca coordenadas da cidade no arquivo cities.json"""
        import json
        import os
        try:
            cities_path = os.path.join(os.path.dirname(__file__), 'cities.json')
            with open(cities_path, 'r') as f:
                cities = json.load(f)
            for city in cities:
                if city['name'].lower() == city_name.lower():
                    return city['lat'], city['lon']
        except Exception as e:
            logger.error(f"Erro ao buscar coordenadas para {city_name}: {e}")
        return None, None

    def settle_all(self):
        """
        Método original de liquidação em lote.
        Itera sobre todos os trades OPEN e tenta liquidar.
        """
        open_trades = self.bankroll.get_open_trades()
        if not open_trades:
            logger.info("Nenhum trade aberto para liquidar.")
            return

        logger.info(f"Liquidando {len(open_trades)} trades abertos...")
        
        for i, trade in enumerate(open_trades):
            try:
                settled_trade = self.settle_trade(trade)
                # Atualiza o trade no bankroll
                self.bankroll.update_trade(trade['id'], settled_trade)
            except Exception as e:
                logger.error(f"Erro ao liquidar trade {trade.get('id', 'unknown')}: {e}", exc_info=True)

        logger.info("Ciclo de liquidação concluído.")