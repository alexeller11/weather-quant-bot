#!/usr/bin/env python3
"""
Settlement Engine - Liquidação de trades com base em resultados reais.
Atualiza calibrador de sigma e modelo ML.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import requests

# NOVO: integração com módulos de calibração e ML
from sigma_calibrator import SigmaCalibrator
from ml_adjuster import MLProbabilityAdjuster
from model import get_calibrator, get_ml_adjuster

logger = logging.getLogger("settlement")

# Instâncias (reutiliza as globais do model.py)
_calibrator = get_calibrator()
_ml_adjuster = get_ml_adjuster()


class SettlementEngine:
    """Resolve trades abertos usando dados observados."""

    def __init__(self):
        # Estratégias de liquidação: 1. Polymarket API, 2. arquivo histórico, 3. previsão curta
        self.sources = ["polymarket", "historical_file", "short_forecast"]

    def get_actual_temperature(self, city: str, date: str) -> Optional[float]:
        """
        Obtém a temperatura real observada. Tenta múltiplas fontes.
        Substitua com a implementação real do seu bot (ex: Open-Meteo historical).
        """
        # Exemplo simplificado: Open-Meteo historical API
        # Você deve adaptar com a lógica real do seu settlement original.
        try:
            # Placeholder: retorna None para forçar fallback
            return None
        except Exception as e:
            logger.error(f"Erro ao obter temperatura real para {city} em {date}: {e}")
            return None

    def settle_trade(self, trade: Dict) -> Dict:
        """
        Liquida um trade individual, atualiza calibração e ML.
        Retorna o trade com status atualizado.
        """
        city = trade['city']
        target_date = trade['date']
        forecast_temp = trade['forecast_temp']
        model_prob = trade['model_prob']
        day_offset = trade['day_offset']

        # 1. Obter temperatura real
        actual_temp = self.get_actual_temperature(city, target_date)

        if actual_temp is None:
            logger.warning(f"Temperatura real não disponível para {city} em {target_date}. Trade permanece OPEN.")
            return trade

        # 2. Determinar resultado
        condition = trade['condition']
        target_temp = trade['target_temp']
        if condition == 'ABOVE':
            won = actual_temp > target_temp
        elif condition == 'BELOW':
            won = actual_temp < target_temp
        else:  # EXACT (aproximado)
            won = abs(actual_temp - target_temp) <= 0.5

        trade['status'] = 'WON' if won else 'LOST'
        trade['actual_temp'] = actual_temp
        trade['settled_at'] = datetime.now().isoformat()

        # 3. Registrar no calibrador de sigma
        _calibrator.record_trade_result(
            city=city,
            day_offset=day_offset,
            predicted_temp=forecast_temp,
            actual_temp=actual_temp
        )

        # 4. Atualizar modelo ML
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

    def settle_open_trades(self, open_trades: List[Dict]):
        """
        Itera sobre todos os trades abertos e tenta liquidá-los.
        Atualiza a lista in-place.
        """
        for i, trade in enumerate(open_trades):
            if trade['status'] == 'OPEN':
                try:
                    open_trades[i] = self.settle_trade(trade)
                except Exception as e:
                    logger.error(f"Falha ao liquidar trade {trade['id']}: {e}", exc_info=True)


# Exemplo de uso independente (caso settlement.py seja executado diretamente)
if __name__ == "__main__":
    # Teste rápido
    engine = SettlementEngine()
    dummy_trade = {
        "id": "test123",
        "city": "New York",
        "condition": "ABOVE",
        "target_temp": 25.0,
        "forecast_temp": 27.0,
        "model_prob": 0.75,
        "price": 0.60,
        "stake": 1.0,
        "date": "2026-05-26",
        "day_offset": 1,
        "status": "OPEN"
    }
    result = engine.settle_trade(dummy_trade)
    print(result)