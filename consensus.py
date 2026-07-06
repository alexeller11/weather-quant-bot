#!/usr/bin/env python3
"""
consensus.py — Motor de Consenso Multi-Fonte

MELHORIAS v2:
- WeatherAPI ativa quando WEATHERAPI_KEY configurada
- Open-Meteo como fonte primária sempre
- Threshold adaptativo: mais rigoroso para EXACT (2.5°C) que ABOVE/BELOW (3°C)
- Log detalhado de divergência por cidade para diagnóstico

AJUSTE v2.1 (2026-06-17):
- EXACT: 1.5°C → 2.5°C (mercados atuais têm divergência natural maior)
- RANGE2: 2.0°C → 3.5°C (buckets de 2°F precisam de margem maior)
- ABOVE/BELOW: mantido em 3.0°C
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
        # AUDITORIA bug #5: o horizonte da WeatherAPI é ~14 dias. Para
        # datas para além disso, `dt` é silenciosamente ignorado e a API
        # devolve "today" or um valor inválido — antes esse valor errado
        # era comparado ao forecast OM (T+N), produzindo divergências
        # espúrias ou consensus falsos. Rejeitamos explicitamente.
        try:
            target = datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception:
            logger.warning(f"[consensus] date_str invalida: {date_str!r}")
            return None
        today = datetime.utcnow().date()
        if (target - today).days > 14:
            logger.info(
                f"[consensus] WeatherAPI nao cobre {date_str} (>"
                f"14d) — usando só Open-Meteo"
            )
            return None
        try:
            r = requests.get(
                "https://api.weatherapi.com/v1/forecast.json",
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

        AUDITORIA bug #5: `temp_openmeteo` deve ser o forecast PURO
        (sem bias correction). Antes recebia o valor corrigido enquanto
        o WeatherAPI tem o seu próprio viés não corrigido — comparação
        sob convenções diferentes inflava falsos "sem consenso" nas
        cidades com maior correção. Comparar os dois crus é equivalente
        a subtrair os vieses relativos; se forem pequenos, consenso OK.

        threshold adaptativo (v2.1 + bug #7):
          EXACT       → 1.5°C (bucket narrow → exigir coerção alta)
          RANGE2      → 2.0°C (bucket de 2°C → máx 1 bucket de diferença)
          ABOVE/BELOW → 3.0°C (threshold original)
        """
        if threshold is None:
            cond = condition.upper()
            if cond == "EXACT":
                threshold = 1.5
            elif cond == "RANGE2":
                threshold = 2.0
            else:
                threshold = 3.0

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
