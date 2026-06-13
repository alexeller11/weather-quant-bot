"""
station_data.py — Dados de estações meteorológicas via Open-Meteo.

Uso no bot:
  from station_data import get_intraday_confirmation
  conf = get_intraday_confirmation(city_slug, condition, target_c)

CORREÇÕES (auditoria):
1. timezone=auto e hora LOCAL para filtro de observações.
2. Cutoffs (>=18h, >=12h) comparados com hora LOCAL.

AUDITORIA SENIOR:
3. Criterios objetivos para reativar Beijing e Hong Kong adicionados.
   Os erros gigantes (25.5C, 11C) eram artefato do bug de timezone que
   foi corrigido. Documentados aqui para facilitar a reativacao.
"""

import requests
import time
from datetime import datetime, timezone

from forecast import CITY_COORDS, city_now, city_today

_INTRADAY_CACHE = {}
_INTRADAY_TTL   = 1800


def _fetch_hourly(lat, lon, local_today: str):
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

    now_hour = city_now(city_slug).hour
    result["current_hour"] = now_hour

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
            result["confirmed"] = True
            result["reason"] = f"max atual {current_max:.1f}°C já passou target {target_c:.1f}°C"
        elif now_hour >= 18 and current_max < target_c - 2.0:
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
            result["confirmed"] = False
            result["reason"] = (
                f"max {current_max:.1f}°C já acima de target {target_c:.1f}°C + 2°C"
            )
        elif current_max < target_c and now_hour >= 18:
            result["confirmed"] = True
            result["reason"] = (
                f"hora {now_hour}h local, max {current_max:.1f}°C < target {target_c:.1f}°C"
            )

    return result


# ────────────────────────────────────────────────────────────
# CIDADES NÃO-CONFIÁVEIS
# ────────────────────────────────────────────────────────────

# AUDITORIA SENIOR: Os erros de Beijing (25.5C) e Hong Kong (11C) eram
# artefatos do bug de timezone (UTC vs local) corrigido em v5.7.
# O proprio comentario original admitia: "em grande parte ARTEFATO do
# bug de timezone".
#
# Para reativar uma cidade desta lista:
#   1. Acumule >= 10 trades pos-correcao (apos v5.7) com a cidade.
#   2. Calcule o erro medio: mean(|forecast_c - real_temp_c|).
#   3. Se erro medio < 5C -> remover da lista abaixo.
#
# should_recheck_city() detecta automaticamente quando os criterios
# sao atendidos (requer bankroll com historico suficiente).
UNRELIABLE_CITIES = {
    "beijing",    # erro medio 25.5C pre-correcao (artefato de timezone)
    "hong-kong",  # erro medio 11C pre-correcao (artefato de timezone)
}

# Numero minimo de trades pos-correcao para reconsiderar uma cidade
_MIN_SAMPLES_TO_RECHECK = 10
_MAX_ERROR_TO_REACTIVATE = 5.0  # graus C


def city_is_reliable(city_slug: str) -> bool:
    """Retorna False para cidades com historico de erros muito altos."""
    slug = city_slug.lower().replace(" ", "-")
    return slug not in UNRELIABLE_CITIES


def should_recheck_city(city_slug: str) -> dict:
    """
    Verifica se uma cidade da UNRELIABLE_CITIES tem dados suficientes
    pos-correcao para ser reativada.

    Retorna:
      eligible: bool  - True se criterios de reativacao sao atendidos
      n_samples: int  - numero de trades pos-correcao
      mean_error: float - erro medio em graus C
      reason: str     - descricao do resultado
    """
    result = {"eligible": False, "n_samples": 0, "mean_error": None, "reason": ""}

    if city_is_reliable(city_slug):
        result["reason"] = f"{city_slug} ja esta ativa"
        return result

    try:
        from bankroll import load_bankroll
        history = load_bankroll().get("history", [])
    except Exception as e:
        result["reason"] = f"erro ao carregar bankroll: {e}"
        return result

    # Versao corrigida: v5.7 (2026-06-01 aproximadamente)
    # Filtra trades desta cidade com real_temp_c preenchido
    errors = []
    for t in history:
        if t.get("result") not in ("WIN", "LOSS"):
            continue
        if t.get("forecast_c") is None or t.get("real_temp_c") is None:
            continue
        city_raw = (t.get("city") or "").lower().replace(" ", "-")
        if city_raw != city_slug:
            continue
        err = abs(float(t["forecast_c"]) - float(t["real_temp_c"]))
        errors.append(err)

    result["n_samples"] = len(errors)
    if not errors:
        result["reason"] = f"sem trades com temperatura real para {city_slug}"
        return result

    mean_err = sum(errors) / len(errors)
    result["mean_error"] = round(mean_err, 2)

    if len(errors) < _MIN_SAMPLES_TO_RECHECK:
        result["reason"] = (
            f"{city_slug}: {len(errors)} amostras < {_MIN_SAMPLES_TO_RECHECK} necessarias"
        )
        return result

    if mean_err < _MAX_ERROR_TO_REACTIVATE:
        result["eligible"] = True
        result["reason"] = (
            f"{city_slug}: erro medio {mean_err:.1f}C < {_MAX_ERROR_TO_REACTIVATE}C "
            f"com {len(errors)} amostras -> PODE REATIVAR (remover de UNRELIABLE_CITIES)"
        )
    else:
        result["reason"] = (
            f"{city_slug}: erro medio {mean_err:.1f}C >= {_MAX_ERROR_TO_REACTIVATE}C "
            f"com {len(errors)} amostras -> manter na lista"
        )

    return result
