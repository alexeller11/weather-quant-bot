#!/usr/bin/env python3
"""
Settlement Engine - Liquidação de trades com base em resultados reais.
Atualiza calibrador de sigma e modelo ML.
Versão compatível com estrutura de funções do projeto.
"""

import logging
import json
import os
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# NOVO: integração com módulos de calibração e ML
from sigma_calibrator import SigmaCalibrator
from ml_adjuster import MLProbabilityAdjuster
from model import get_calibrator, get_ml_adjuster
import bankroll

logger = logging.getLogger("settlement")

_calibrator = get_calibrator()
_ml_adjuster = get_ml_adjuster()

def get_actual_temperature(lat: float, lon: float, date: str) -> Optional[float]:
    """Consulta a temperatura máxima real na Open-Meteo Archive API."""
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

def _get_city_coordinates(city_name: str) -> tuple:
    """Busca coordenadas da cidade no arquivo cities.json"""
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

def settle_trade(trade: Dict) -> Dict:
    """Liquida um trade individual, atualiza calibração e ML."""
    if trade.get('status') != 'OPEN':
        return trade

    city = trade['city']
    date = trade['date']
    forecast_temp = trade['forecast_temp']
    model_prob = trade.get('model_prob', 0.5)
    day_offset = trade.get('day_offset', 1)
    lat = trade.get('lat')
    lon = trade.get('lon')

    if lat is None or lon is None:
        logger.warning(f"Trade {trade['id']} sem coordenadas. Tentando buscar...")
        lat, lon = _get_city_coordinates(city)
        if lat is None:
            logger.error(f"Não foi possível obter coordenadas para {city}")
            return trade

    actual_temp = get_actual_temperature(lat, lon, date)
    if actual_temp is None:
        logger.warning(f"Temperatura real não disponível para {city} em {date}.")
        return trade

    condition = trade['condition']
    target_temp = trade['target_temp']
    if condition == 'ABOVE':
        won = actual_temp > target_temp
    elif condition == 'BELOW':
        won = actual_temp < target_temp
    else:
        won = abs(actual_temp - target_temp) <= 0.5

    trade['status'] = 'WON' if won else 'LOST'
    trade['actual_temp'] = actual_temp
    trade['settled_at'] = datetime.now().isoformat()

    _calibrator.record_trade_result(
        city=city,
        day_offset=day_offset,
        predicted_temp=forecast_temp,
        actual_temp=actual_temp
    )

    _ml_adjuster.update(
        model_prob=model_prob,
        day_offset=day_offset,
        city=city,
        calibrator=_calibrator,
        trade_success=won
    )

    logger.info(f"Trade {trade['id']} liquidado: {trade['status']} (forecast={forecast_temp}, actual={actual_temp})")
    return trade

def settle_all():
    """Liquida todos os trades abertos."""
    open_trades = bankroll.get_open_trades()
    if not open_trades:
        logger.info("Nenhum trade aberto para liquidar.")
        return

    logger.info(f"Liquidando {len(open_trades)} trades abertos...")
    
    for trade in open_trades:
        try:
            settled_trade = settle_trade(trade)
            bankroll.update_trade(trade['id'], settled_trade)
        except Exception as e:
            logger.error(f"Erro ao liquidar trade {trade.get('id', 'unknown')}: {e}", exc_info=True)

    logger.info("Ciclo de liquidação concluído.")