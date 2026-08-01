#!/usr/bin/env python3
"""
consensus.py — Motor de Consenso Multi-Fonte

Open-Meteo é a fonte primária; WeatherAPI é a confirmação, quando há
WEATHERAPI_KEY. Os thresholds vêm de config (CONSENSUS_MAX_DIFF_*).

O threshold de RANGE2 estava em 3.5°C — mais de 3x a largura de um bucket
de 2°F (1.11°C), ou seja, não filtrava nada relevante justamente no tipo
de mercado mais sensível. Agora 1.5°C por default.

Sem a 2ª fonte, `consensus` continua True por omissão (é o que acontecia
em todo o histórico, por falta de chave), mas `temp_secondary` fica None
para o caller poder exigir confirmação via REQUIRE_CONSENSUS.
"""

import os
import logging
from typing import Optional, Dict

import requests

from config import (
    CONSENSUS_MAX_DIFF_RANGE2,
    CONSENSUS_MAX_DIFF_EXACT,
    CONSENSUS_MAX_DIFF_DEFAULT,
)

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

        Thresholds de config: CONSENSUS_MAX_DIFF_EXACT / _RANGE2 / _DEFAULT.
        """
        if threshold is None:
            cond = condition.upper()
            if cond == "EXACT":
                threshold = CONSENSUS_MAX_DIFF_EXACT
            elif cond == "RANGE2":
                threshold = CONSENSUS_MAX_DIFF_RANGE2
            else:
                threshold = CONSENSUS_MAX_DIFF_DEFAULT

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
