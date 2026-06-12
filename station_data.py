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

CORREÇÕES (auditoria):
1. Os dados horários agora são pedidos com timezone=auto e o "hoje" é o
   dia LOCAL da cidade. Antes tudo era UTC: para Los Angeles, "18h"
   significava 11h da manhã local, e o filtro de "horas já passadas"
   misturava observações do dia local errado.
2. Os cutoffs de decisão (>=18h, >=12h) agora são comparados com a HORA
   LOCAL da cidade — a heurística é sobre o ciclo diurno local ("já é
   tarde, a máxima do dia já aconteceu"), não sobre o relógio UTC.
"""

import requests
import time
from datetime import datetime, timezone

from forecast import CITY_COORDS, city_now, city_today

_INTRADAY_CACHE = {}
_INTRADAY_TTL   = 1800  # 30 min


def _fetch_hourly(lat, lon, local_today: str):
    """
    Busca temperatura horária do DIA LOCAL da cidade via Open-Meteo.
    timezone=auto faz a API devolver timestamps já na hora local da
    coordenada, e start/end_date interpretados como dia local.
    """
    cache_key = (round(lat, 2), round(lon, 2), local_today)
    now = time.time()
    if cache_key in _INTRADAY_CACHE:
        age = now - _INTRADAY_CACHE[cache_key]["ts"]
        if age < _INTRADAY_TTL:
            return _INTRADAY_CACHE[cache_key]["data"]

    try:
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude":      lat,
            "longitude":     lon,
            "hourly":        "temperature_2m",
            "timezone":      "auto",
            "start_date":    local_today,
            "end_date":      local_today,
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

    Para mercados que resolvem HOJE (dia local da cidade):
      - Pega temperatura máxima horária observada até agora (hora local)
      - Se max_atual já passou o target ABOVE → prob ~0.95 → confirma
      - Se hora local > 18:00 e max_atual < target - 2°C → prob ~0.05 → rejeita

    Para mercados futuros (D+2, D+3): retorna neutro (não há dados ainda).

    Retorna:
      confirmed  — True = sinal forte, False = sinal fraco, None = neutro
      current_max — temperatura máxima observada hoje (ou None)
      current_hour — hora LOCAL da cidade
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
    local_today = city_today(city_slug)
    hourly = _fetch_hourly(lat, lon, local_today)
    if not hourly:
        return result

    # Hora LOCAL da cidade (não UTC): a heurística é sobre o ciclo diurno.
    now_hour = city_now(city_slug).hour
    result["current_hour"] = now_hour

    # Filtra apenas horas já passadas (dados observados, não previstos).
    # Com timezone=auto, os timestamps horários vêm em hora LOCAL,
    # comparável diretamente com now_hour local.
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
            # Tarde (hora local), bem abaixo do target — muito improvável resolver YES
            result["confirmed"] = False
            result["reason"] = (
                f"hora {now_hour}h local, max {current_max:.1f}°C < "
                f"target {target_c:.1f}°C - 2°C — improvável superar"
            )
        else:
            result["reason"] = (
                f"max até agora: {current_max:.1f}°C, target: {target_c:.1f}°C "
                f"(hora {now_hour}h local)"
            )

    elif condition == "BELOW":
        if current_max >= target_c + 2.0 and now_hour >= 12:
            # Já quente demais, tarde (hora local) — não vai resolver BELOW
            result["confirmed"] = False
            result["reason"] = (
                f"max {current_max:.1f}°C já acima de target {target_c:.1f}°C + 2°C"
            )
        elif current_max < target_c and now_hour >= 18:
            # Tarde (hora local), ainda abaixo — muito provável resolver BELOW
            result["confirmed"] = True
            result["reason"] = (
                f"hora {now_hour}h local, max {current_max:.1f}°C < target {target_c:.1f}°C"
            )

    return result


# Mapeamento de cidades problemáticas com erro sistemático alto
# Dados dos 39 trades: eliminar cidades onde erro de forecast > 5°C médio
# NOTA (auditoria): os erros gigantes de Beijing (25.5°C) e Hong Kong (11°C)
# eram em grande parte ARTEFATO do bug de timezone (settlement comparava a
# máxima do dia UTC com mercados que resolvem pelo dia local — para a Ásia a
# diferença é enorme). Com as correções de timezone, estas cidades tendem a
# voltar a ser utilizáveis; mantemos a lista por segurança até que novas
# estatísticas pós-correção confirmem.
UNRELIABLE_CITIES = {
    "beijing",    # erro médio 25.5°C (artefato de timezone + possível estação)
    "hong-kong",  # erro médio 11°C (artefato de timezone + possível estação)
}


def city_is_reliable(city_slug: str) -> bool:
    """Retorna False para cidades com histórico de erros de forecast muito altos."""
    slug = city_slug.lower().replace(" ", "-")
    return slug not in UNRELIABLE_CITIES
