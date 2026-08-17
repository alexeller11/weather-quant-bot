#!/usr/bin/env python3
"""
consensus.py — Motor de Consenso Multi-Fonte

Open-Meteo é a fonte primária; WeatherAPI é a confirmação, quando há
WEATHERAPI_KEY. Os thresholds vêm de config (CONSENSUS_MAX_DIFF_*).

Sem a 2ª fonte, `consensus` continua True por omissão (é o que acontecia
em todo o histórico, por falta de chave), mas `temp_secondary` fica None
para o caller poder exigir confirmação via REQUIRE_CONSENSUS.

CORREÇÃO 2026-08-03 — viés sistemático entre fontes:
Com WEATHERAPI_KEY configurada em produção, o consenso ficou ativo de
verdade e passou a bloquear 46% de todas as tentativas de trade ("sem
consenso"). Os valores reais nos logs mostravam WeatherAPI
consistentemente ~2-3°C MAIS QUENTE que Open-Meteo, sempre na mesma
direção — não é ruído aleatório em torno de zero, é viés sistemático
entre as duas fontes (estações/modelos diferentes). Comparar a diferença
BRUTA contra um threshold apertado (1.5°C, ajustado nesta mesma sessão
para não deixar passar bucket de 2°F) confundia esse viés com divergência
real de previsão.

Agora ConsensusBiasTracker estima (WA − OM) por cidade com média móvel e
shrinkage — mesmo padrão de sigma_calibrator.py — e o viés estimado é
removido do valor bruto ANTES de comparar ao threshold. Nos primeiros
CONSENSUS_BIAS_MIN_SAMPLES por cidade, sem estimativa confiável ainda, o
viés usado é 0 (comportamento antigo) e a amostra vai sendo acumulada a
cada chamada, tenha ela virado trade ou não.
"""

import json
import os
import logging
import time
import unicodedata
from datetime import datetime, timezone
from typing import Optional, Dict, List

import requests
from model import delta_to_celsius, to_celsius

from config import (
    CONSENSUS_MAX_DIFF_RANGE2,
    CONSENSUS_MAX_DIFF_EXACT,
    CONSENSUS_MAX_DIFF_DEFAULT,
    CONSENSUS_MAX_RAW_DIFF,
    CONSENSUS_BIAS_WINDOW,
    CONSENSUS_BIAS_MIN_SAMPLES,
    CONSENSUS_BIAS_SHRINK_K,
)

logger = logging.getLogger(__name__)

_BIAS_FILE = "consensus_bias.json"
_BIAS_DB_KEY = "consensus_bias_v1"


def _strip_accents(text: str) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", str(text))
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _city_key(city: Optional[str]) -> str:
    if not city:
        return "_global"
    return _strip_accents(city).strip().lower().replace(" ", "-")


class ConsensusBiasTracker:
    """
    Rastreia o viés (WeatherAPI − Open-Meteo) por cidade, para remover
    diferença sistemática antes de julgar "sem consenso".

    Persistência: arquivo local + PostgreSQL quando DATABASE_URL está
    configurada — mesmo padrão de sigma_calibrator.SigmaCalibrator.
    """

    def __init__(self):
        self.data: Dict[str, List[float]] = self._load()

    def _load(self) -> Dict:
        data = self._load_from_db()
        if data:
            return data
        if os.path.exists(_BIAS_FILE):
            try:
                with open(_BIAS_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"[consensus] {_BIAS_FILE} corrompido: {e}")
        return {}

    def _load_from_db(self) -> Dict:
        url = os.environ.get("DATABASE_URL", "")
        if not url:
            return {}
        try:
            import psycopg2
            conn = psycopg2.connect(url, sslmode="require")
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS kv_store (
                        key TEXT PRIMARY KEY,
                        value JSONB NOT NULL,
                        saved_at TIMESTAMP DEFAULT NOW()
                    )
                """)
                conn.commit()
                cur.execute("SELECT value FROM kv_store WHERE key = %s", (_BIAS_DB_KEY,))
                row = cur.fetchone()
            conn.close()
            return row[0] if row else {}
        except Exception as e:
            logger.debug(f"[consensus] db load: {e}")
            return {}

    def _save(self):
        try:
            with open(_BIAS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"[consensus] {_BIAS_FILE} save: {e}")

        url = os.environ.get("DATABASE_URL", "")
        if not url:
            return
        try:
            import psycopg2
            conn = psycopg2.connect(url, sslmode="require")
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS kv_store (
                        key TEXT PRIMARY KEY,
                        value JSONB NOT NULL,
                        saved_at TIMESTAMP DEFAULT NOW()
                    )
                """)
                cur.execute("""
                    INSERT INTO kv_store (key, value)
                    VALUES (%s, %s)
                    ON CONFLICT (key) DO UPDATE
                        SET value = EXCLUDED.value, saved_at = NOW()
                """, (_BIAS_DB_KEY, json.dumps(self.data)))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug(f"[consensus] db save: {e}")

    def record(self, city: Optional[str], signed_diff: float):
        """signed_diff = temp_weatherapi - temp_openmeteo."""
        key = _city_key(city)
        entries = self.data.setdefault(key, [])
        entries.append(round(signed_diff, 3))
        self.data[key] = entries[-CONSENSUS_BIAS_WINDOW:]
        self._save()

    def get_bias(self, city: Optional[str]):
        """Retorna (viés_estimado, n_amostras). Viés=0 até MIN_SAMPLES."""
        entries = self.data.get(_city_key(city), [])
        n = len(entries)
        if n < CONSENSUS_BIAS_MIN_SAMPLES:
            return 0.0, n
        weight = n / (n + CONSENSUS_BIAS_SHRINK_K)
        raw_bias = sum(entries) / n
        return weight * raw_bias, n


_bias_tracker = ConsensusBiasTracker()


def _bucket_contains_temp(
    temp_c: float,
    condition: str,
    target: Optional[float],
    unit: str,
    target_lo=None,
    target_hi=None,
) -> Optional[bool]:
    cond = str(condition).upper()
    if cond not in ("EXACT", "RANGE2") or target is None:
        return None
    unit = str(unit or "C").upper()
    target_c = to_celsius(float(target), unit)
    if cond == "RANGE2" and target_lo is not None and target_hi is not None:
        lo_c = to_celsius(float(target_lo), unit)
        hi_c = to_celsius(float(target_hi), unit)
    else:
        half = delta_to_celsius(0.5 if cond == "EXACT" else 1.0, unit)
        lo_c, hi_c = target_c - half, target_c + half
    if lo_c > hi_c:
        lo_c, hi_c = hi_c, lo_c
    return lo_c <= float(temp_c) <= hi_c


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
        city: Optional[str] = None,
        target: Optional[float] = None,
        unit: str = "C",
        target_lo=None,
        target_hi=None,
    ) -> Dict:
        """
        Verifica consenso entre Open-Meteo e WeatherAPI, descontando o
        viés sistemático estimado por cidade (ver ConsensusBiasTracker).

        Thresholds de config: CONSENSUS_MAX_DIFF_EXACT / _RANGE2 / _DEFAULT.
        `city` é opcional; sem ele, o viés é rastreado globalmente
        (chave "_global") — menos preciso, mas nunca quebra o caller.
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
            "raw_diff":       None,
            "bias_removed":   None,
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

        signed_diff = temp2 - temp_openmeteo  # WA - OM
        if abs(signed_diff) > CONSENSUS_MAX_RAW_DIFF:
            result["temp_secondary"] = None
            result["raw_diff"] = round(signed_diff, 2)
            result["reason"] = (
                "WeatherAPI descartada por divergência bruta absurda: "
                f"OM={temp_openmeteo:.1f}°C WA={temp2:.1f}°C "
                f"(bruta {signed_diff:+.1f}°C > {CONSENSUS_MAX_RAW_DIFF:.1f}°C) — "
                "usando só Open-Meteo"
            )
            logger.warning(f"[consensus] {result['reason']}")
            return result

        bias, n_bias = _bias_tracker.get_bias(city)
        _bias_tracker.record(city, signed_diff)

        corrected_diff = abs(signed_diff - bias)

        result["temp_secondary"] = temp2
        result["diff"] = round(corrected_diff, 2)
        result["raw_diff"] = round(signed_diff, 2)
        result["bias_removed"] = round(bias, 2)

        primary_in_bucket = _bucket_contains_temp(
            temp_openmeteo, condition, target, unit, target_lo, target_hi
        )
        secondary_in_bucket = _bucket_contains_temp(
            temp2, condition, target, unit, target_lo, target_hi
        )

        detail = (
            f"OM={temp_openmeteo:.1f}°C WA={temp2:.1f}°C "
            f"(bruta {signed_diff:+.1f}°C, viés {bias:+.1f}°C n={n_bias}, "
            f"resíduo {corrected_diff:.1f}°C)"
        )

        if (
            primary_in_bucket is not None
            and secondary_in_bucket is not None
            and primary_in_bucket == secondary_in_bucket
        ):
            result["consensus"] = True
            outcome = "dentro" if primary_in_bucket else "fora"
            result["reason"] = f"Consenso OK por bucket: ambas fontes {outcome}; {detail}"
        elif corrected_diff <= threshold:
            result["consensus"] = True
            result["reason"] = f"Consenso OK: {detail} ≤ {threshold}°C"
        else:
            result["consensus"] = False
            result["reason"] = f"Sem consenso: {detail} > {threshold}°C"
            logger.info(f"[consensus] BLOQUEADO — {result['reason']}")

        return result
