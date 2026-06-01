"""
station_data.py — Dados de estações meteorológicas específicas via Open-Meteo.

PROBLEMA IDENTIFICADO: A Polymarket usa temperaturas de estações específicas
para settlement (ex.: aeroporto para Londres, Central Park para NYC).
Open-Meteo retorna modelo gridado que pode divergir 2-6°C da estação real.

Este módulo busca dados horários de temperatura atual via Open-Meteo para
confirmar tendência intra-dia — se o dia está claramente quente/frio,
a probabilidade de resolução é muito maior do que a previsão D+1 indicaria.

Uso no bot:
  from station_data import get_intraday_confirmation
  conf = get_intraday_confirmation(city_slug, condition, target_c)
  # retorna {'confirmed': bool, 'current_max': float, 'reason': str}
"""

import requests
import time
from datetime import datetime, timezone

from forecast import CITY_COORDS

_INTRADAY_CACHE = {}
_INTRADAY_TTL   = 1800  # 30 min


def _fetch_hourly(lat, lon):
    """Busca temperatura horária de hoje via Open-Meteo."""
    cache_key = (round(lat, 2), round(lon, 2))
    now = time.time()
    if cache_key in _INTRADAY_CACHE:
        age = now - _INTRADAY_CACHE[cache_key]["ts"]
        if age < _INTRADAY_TTL:
            return _INTRADAY_CACHE[cache_key]["data"]

    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude":      lat,
            "longitude":     lon,
            "hourly":        "temperature_2m",
            "timezone":      "UTC",
            "start_date":    today,
            "end_date":      today,
            "forecast_days": 1,
        }
        r = requests.get(url, params=params, timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
        temps = data.get("hourly", {}).get("temperature_2m", [])
        times = data.get("hourly", {}).get("time", [])
        _INTRADAY_CACHE[cache_key] = {"data": list(zip(times, temps)), "ts": now}
        return list(zip(times, temps))
    except Exception as e:
        print(f"[station_data] erro: {e}")
        return None


def get_intraday_confirmation(city_slug: str, condition: str, target_c: float) -> dict:
    """
    Verifica tendência intra-dia para confirmar ou rejeitar entrada.

    Para mercados que resolvem HOJE:
      - Pega temperatura máxima horária observada até agora
      - Se max_atual já passou o target ABOVE → prob ~0.95 → confirma
      - Se hora atual > 18:00 UTC e max_atual < target - 2°C → prob ~0.05 → rejeita

    Para mercados futuros (D+2, D+3): retorna neutro (não há dados ainda).

    Retorna:
      confirmed  — True = sinal forte, False = sinal fraco, None = neutro
      current_max — temperatura máxima observada hoje (ou None)
      current_hour — hora UTC atual
      reason — descrição do veredito
    """
    result = {
        "confirmed": None,
        "current_max": None,
        "current_hour": None,
        "reason": "sem dados intra-dia",
    }

    if city_slug not in CITY_COORDS:
        return result

    lat, lon = CITY_COORDS[city_slug]
    hourly = _fetch_hourly(lat, lon)
    if not hourly:
        return result

    now_hour = datetime.now(timezone.utc).hour
    result["current_hour"] = now_hour

    # Filtra apenas horas já passadas (dados observados, não previstos)
    observed = []
    for time_str, temp in hourly:
        try:
            h = int(time_str[11:13])
            if h <= now_hour and temp is not None:
                observed.append(float(temp))
        except Exception:
            continue

    if not observed:
        result["reason"] = "sem observações horárias ainda"
        return result

    current_max = max(observed)
    result["current_max"] = round(current_max, 1)

    condition = condition.upper()

    if condition == "ABOVE":
        if current_max > target_c:
            # Já superou o target — mercado resolve YES com certeza
            result["confirmed"] = True
            result["reason"] = f"max atual {current_max:.1f}°C já passou target {target_c:.1f}°C"
        elif now_hour >= 18 and current_max < target_c - 2.0:
            # Tarde, bem abaixo do target — muito improvável resolver YES
            result["confirmed"] = False
            result["reason"] = (
                f"hora {now_hour}h UTC, max {current_max:.1f}°C < "
                f"target {target_c:.1f}°C - 2°C — improvável superar"
            )
        else:
            result["reason"] = (
                f"max até agora: {current_max:.1f}°C, target: {target_c:.1f}°C "
                f"(hora {now_hour}h UTC)"
            )

    elif condition == "BELOW":
        if current_max >= target_c + 2.0 and now_hour >= 12:
            # Já quente demais, tarde — não vai resolver BELOW
            result["confirmed"] = False
            result["reason"] = (
                f"max {current_max:.1f}°C já acima de target {target_c:.1f}°C + 2°C"
            )
        elif current_max < target_c and now_hour >= 18:
            # Tarde, ainda abaixo — muito provável resolver BELOW
            result["confirmed"] = True
            result["reason"] = (
                f"hora {now_hour}h UTC, max {current_max:.1f}°C < target {target_c:.1f}°C"
            )

    return result


# Mapeamento de cidades problemáticas com erro sistemático alto
# Dados dos 39 trades: eliminar cidades onde erro de forecast > 5°C médio
UNRELIABLE_CITIES = {
    "beijing",    # erro médio 25.5°C (provável problema de estação)
    "hong-kong",  # erro médio 11°C (possível problema de estação/timezone)
}


def city_is_reliable(city_slug: str) -> bool:
    """Retorna False para cidades com histórico de erros de forecast muito altos."""
    slug = city_slug.lower().replace(" ", "-")
    return slug not in UNRELIABLE_CITIES
