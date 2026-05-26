"""
Motor de Consenso Multi-Fonte para Previsão de Temperatura
Autor: Integração Weather-Quant-Bot
Descrição: Consulta múltiplas APIs de previsão e retorna um veredito de consenso,
           aumentando a assertividade do sinal de trading.
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple
import requests

logger = logging.getLogger(__name__)

class ConsensusEngine:
    """
    Compara previsões de temperatura de fontes distintas para validar sinais.
    Fontes: Open-Meteo (já existente) e WeatherAPI (requer chave).
    """

    def __init__(self, weatherapi_key: Optional[str] = None):
        self.weatherapi_key = weatherapi_key or os.getenv("WEATHERAPI_KEY")
        if not self.weatherapi_key:
            logger.warning(
                "WeatherAPI key não configurada. "
                "Motor de consenso funcionará apenas com Open-Meteo."
            )

    def get_weatherapi_forecast(self, lat: float, lon: float, date_str: str) -> Optional[float]:
        """
        Obtém previsão de temperatura máxima para uma data da WeatherAPI.
        Retorna None em caso de falha.
        """
        if not self.weatherapi_key:
            return None
        try:
            url = "http://api.weatherapi.com/v1/forecast.json"
            params = {
                "key": self.weatherapi_key,
                "q": f"{lat},{lon}",
                "dt": date_str,
                "days": 1,
                "aqi": "no",
                "alerts": "no"
            }
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            day = data["forecast"]["forecastday"][0]["day"]
            temp_c = day["maxtemp_c"]
            return temp_c
        except Exception as e:
            logger.error(f"Erro ao consultar WeatherAPI: {e}")
            return None

    def consensus_temperature(
        self,
        lat: float,
        lon: float,
        date_str: str,
        temp_openmeteo: float,
        threshold: float = 3.0
    ) -> Dict:
        """
        Compara a previsão da Open-Meteo (já calculada) com a da WeatherAPI.
        Retorna dicionário com status do consenso e detalhes.

        Parâmetros:
        - temp_openmeteo: temperatura prevista pela fonte primária (Open-Meteo).
        - threshold: diferença máxima em °C para considerar consenso (default 3.0°C).
        """
        result = {
            "consensus": False,
            "temp_primary": temp_openmeteo,
            "temp_secondary": None,
            "diff": None,
            "reason": ""
        }

        if not self.weatherapi_key:
            result["reason"] = "WeatherAPI key ausente, usando apenas Open-Meteo"
            result["consensus"] = True  # fallback para não travar o bot
            return result

        temp_secondary = self.get_weatherapi_forecast(lat, lon, date_str)
        if temp_secondary is None:
            result["reason"] = "Falha na consulta à WeatherAPI"
            return result

        result["temp_secondary"] = temp_secondary
        diff = abs(temp_openmeteo - temp_secondary)
        result["diff"] = round(diff, 2)

        if diff <= threshold:
            result["consensus"] = True
            result["reason"] = f"Consenso OK (diferença {diff}°C)"
        else:
            result["reason"] = f"Sem consenso (diferença {diff}°C > {threshold}°C)"

        return result