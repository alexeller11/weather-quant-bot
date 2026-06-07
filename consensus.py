#!/usr/bin/env python3
"""
consensus.py — Motor de Consenso Multi-Fonte

MELHORIAS v2:
- WeatherAPI ativa quando WEATHERAPI_KEY configurada
- Open-Meteo como fonte primária sempre
- Threshold adaptativo: mais rigoroso para EXACT (1.5°C) que ABOVE/BELOW (3°C)
- Log detalhado de divergência por cidade para diagnóstico
"""

import os
import logging
from datetime import datetime
from typing import Optional, Dict

import requests

logger = logging.getLogger(__name__)


class ConsensusEngine:
    def __init__(self, weatherapi_key: Optional[str] = None):
        self.weatherapi_key = weatherapi_key or os.environ.get("WEATHERAPI_KEY", "").strip()
        if not self.weatherapi_key:
            logger.warning(
                "WeatherAPI key não configurada. "
                "Motor de consenso funcionará apenas com Open-Meteo."
            )
        else:
            logger.info("WeatherAPI key configurada — consenso duplo ativo.")

    def get_weatherapi_forecast(
        self, lat: float, lon: float, date_str: str
    ) -> Optional[float]:
        if not self.weatherapi_key:
            return None
        try:
            r = requests.get(
                "http://api.weatherapi.com/v1/forecast.json",
                params={
                    "key":  self.weatherapi_key,
                    "q":    f"{lat},{lon}",
                    "dt":   date_str,
                    "days": 1,
                    "aqi":  "no",
                    "alerts": "no",
                },
                timeout=10,
            )
            r.raise_for_status()
            return float(r.json()["forecast"]["forecastday"][0]["day"]["maxtemp_c"])
        except Exception as e:
            logger.warning(f"[consensus] WeatherAPI erro: {e}")
            return None

    def consensus_temperature(
        self,
        lat: float,
        lon: float,
        date_str: str,
        temp_openmeteo: float,
        condition: str = "ABOVE",
        threshold: float = None,
    ) -> Dict:
        """
        Verifica consenso entre Open-Meteo e WeatherAPI.

        threshold adaptativo:
          EXACT   → 1.5°C  (mais exigente — bucket de 1°C)
          ABOVE/BELOW → 3.0°C
          RANGE2  → 2.0°C
        """
        if threshold is None:
            cond = condition.upper()
            threshold = 1.5 if cond == "EXACT" else (2.0 if cond == "RANGE2" else 3.0)

        result = {
            "consensus":      True,   # default: passa se WeatherAPI indisponível
            "temp_primary":   temp_openmeteo,
            "temp_secondary": None,
            "diff":           None,
            "threshold":      threshold,
            "reason":         "",
        }

        if not self.weatherapi_key:
            result["reason"] = "WeatherAPI ausente — usando só Open-Meteo"
            return result

        temp2 = self.get_weatherapi_forecast(lat, lon, date_str)
        if temp2 is None:
            result["reason"] = "WeatherAPI indisponível — usando só Open-Meteo"
            return result

        diff = abs(temp_openmeteo - temp2)
        result["temp_secondary"] = temp2
        result["diff"] = round(diff, 2)

        if diff <= threshold:
            result["consensus"] = True
            result["reason"] = (
                f"Consenso OK: OM={temp_openmeteo:.1f}°C WA={temp2:.1f}°C "
                f"(dif {diff:.1f}°C ≤ {threshold}°C)"
            )
        else:
            result["consensus"] = False
            result["reason"] = (
                f"Sem consenso: OM={temp_openmeteo:.1f}°C WA={temp2:.1f}°C "
                f"(dif {diff:.1f}°C > {threshold}°C)"
            )
            logger.info(f"[consensus] BLOQUEADO — {result['reason']}")

        return result
