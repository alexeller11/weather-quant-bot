# =========================================================
# FORECAST ENGINE — OPEN METEO (COM TTL + BIAS CORRECTION)
#
# CORREÇÕES DA AUDITORIA (v5.7):
#
# 1. TIMEZONE: as chamadas ao Open-Meteo usavam timezone=UTC.
#    Com timezone=UTC o "temperature_2m_max" diário é o máximo do
#    DIA UTC, não do dia LOCAL da cidade. A Polymarket resolve pelo
#    dia local. Para Tóquio/Seul/Pequim/Hong Kong (UTC+8/+9) e costa
#    oeste dos EUA (UTC-7/-8) isso desloca o dado em até um dia e
#    mistura dois dias locais — exatamente o que gerou os "erros
#    médios de 25.5°C (Beijing) e 11°C (Hong Kong)" anotados em
#    station_data.py. Agora: timezone=auto (agregação no dia local).
#
# 2. CITY_TZ + city_today(): o dia "hoje" passa a ser o dia local da
#    cidade, usado por bot.py (day_offset), gamma_parser (slug da
#    data) e settlement (prontidão de liquidação).
#
# 3. compute_bias(): deduplicação por (market_date, forecast_day).
#    Antes, vários trades no MESMO dia/cidade (ex.: 3 buckets EXACT
#    de Toronto em 2026-06-07) contavam o mesmo erro 3×, enviesando
#    a média (pseudo-replicação).
#
# MANTIDO: sigma base {1:4.0, 2:4.5, 3:5.0, ...} e ajustes por cidade.
# =========================================================

import requests
import time
from datetime import datetime, timezone, timedelta

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9 (não esperado em produção)
    ZoneInfo = None

# =========================================================
# COORDS
# =========================================================

CITY_COORDS = {
    "new-york":    (40.7128, -74.0060),
    "london":      (51.5072, -0.1276),
    "paris":       (48.8566, 2.3522),
    "hong-kong":   (22.3193, 114.1694),
    "tokyo":       (35.6762, 139.6503),
    "seoul":       (37.5665, 126.9780),
    "beijing":     (39.9042, 116.4074),
    "sao-paulo":   (-23.5505, -46.6333),
    "milan":       (45.4642, 9.1900),
    "los-angeles": (34.0522, -118.2437),
    "houston":     (29.7604, -95.3698),
    "austin":      (30.2672, -97.7431),
    "denver":      (39.7392, -104.9903),
    "seattle":     (47.6062, -122.3321),
    "chicago":     (41.8781, -87.6298),
    "phoenix":     (33.4484, -112.0740),
    "miami":       (25.7617, -80.1918),
    "atlanta":     (33.7490, -84.3880),
    "boston":      (42.3601, -71.0589),
    "toronto":     (43.6532, -79.3832),
    "madrid":      (40.4168, -3.7038),
    "mexico-city": (19.4326, -99.1332),
}

# Fuso IANA de cada cidade — os mercados da Polymarket são definidos
# pelo dia LOCAL da cidade.
CITY_TZ = {
    "new-york":    "America/New_York",
    "london":      "Europe/London",
    "paris":       "Europe/Paris",
    "hong-kong":   "Asia/Hong_Kong",
    "tokyo":       "Asia/Tokyo",
    "seoul":       "Asia/Seoul",
    "beijing":     "Asia/Shanghai",
    "sao-paulo":   "America/Sao_Paulo",
    "milan":       "Europe/Rome",
    "los-angeles": "America/Los_Angeles",
    "houston":     "America/Chicago",
    "austin":      "America/Chicago",
    "denver":      "America/Denver",
    "seattle":     "America/Los_Angeles",
    "chicago":     "America/Chicago",
    "phoenix":     "America/Phoenix",
    "miami":       "America/New_York",
    "atlanta":     "America/New_York",
    "boston":      "America/New_York",
    "toronto":     "America/Toronto",
    "madrid":      "Europe/Madrid",
    "mexico-city": "America/Mexico_City",
}


def city_now(city_slug):
    """datetime atual no fuso da cidade (fallback: UTC)."""
    tz_name = CITY_TZ.get(city_slug)
    if tz_name and ZoneInfo is not None:
        try:
            return datetime.now(ZoneInfo(tz_name))
        except Exception:
            pass
    return datetime.now(timezone.utc)


def city_today(city_slug):
    """'Hoje' no fuso da cidade, como string ISO 'YYYY-MM-DD'."""
    return city_now(city_slug).strftime("%Y-%m-%d")


# =========================================================
# BIAS CORRECTION
# =========================================================

BIAS_WINDOW_DAYS = 21
BIAS_MIN_SAMPLES = 3

_BIAS_CACHE = {}
_BIAS_CACHE_TTL = 3600


def _city_raw_to_slug(city_raw, slug_normalize):
    slug = slug_normalize.get(city_raw)
    if slug:
        return slug
    return city_raw.lower().replace(" ", "-").replace("_", "-").strip()


def compute_bias(city_slug):
    """
    Calcula bias médio do Open-Meteo para a cidade.
    bias = mean(forecast_c - real_temp_c) nos trades fechados.
    Cada (market_date, forecast_day) conta UMA vez — vários trades no
    mesmo dia (vários buckets) não multiplicam a mesma amostra.
    Retorna (bias_c, n_samples). Sem amostras suficientes: (0.0, 0).
    """
    now = time.time()

    cached = _BIAS_CACHE.get(city_slug)
    if cached:
        bias_c, n, computed_at = cached
        if now - computed_at < _BIAS_CACHE_TTL:
            return bias_c, n

    try:
        from bankroll import load_bankroll
        from config import CITY_SLUG_NORMALIZE
    except Exception as e:
        print(f"[bias] erro ao importar bankroll: {e}")
        return 0.0, 0

    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=BIAS_WINDOW_DAYS)

    try:
        history = load_bankroll().get("history", [])
    except Exception as e:
        print(f"[bias] erro ao carregar bankroll: {e}")
        return 0.0, 0

    samples = {}
    for t in history:
        if t.get("result") not in ("WIN", "LOSS"):
            continue
        if t.get("forecast_c") is None or t.get("real_temp_c") is None:
            continue

        city_raw = t.get("city", "")
        t_slug = _city_raw_to_slug(city_raw, CITY_SLUG_NORMALIZE)
        if t_slug != city_slug:
            continue

        exit_time_str = t.get("exit_time", "")
        if exit_time_str:
            try:
                exit_dt = datetime.fromisoformat(exit_time_str.replace("Z", ""))
                if exit_dt.tzinfo is not None:
                    exit_dt = exit_dt.astimezone(timezone.utc).replace(tzinfo=None)
                if exit_dt < cutoff:
                    continue
            except Exception:
                pass

        err = float(t["forecast_c"]) - float(t["real_temp_c"])
        # Deduplicação: uma amostra por dia de mercado e horizonte
        sample_key = (str(t.get("market_date", "")), int(t.get("forecast_day", 1) or 1))
        samples[sample_key] = err

    errors = list(samples.values())

    if len(errors) < BIAS_MIN_SAMPLES:
        _BIAS_CACHE[city_slug] = (0.0, len(errors), now)
        return 0.0, len(errors)

    bias_c = sum(errors) / len(errors)
    _BIAS_CACHE[city_slug] = (round(bias_c, 3), len(errors), now)

    print(
        f"[bias] {city_slug}: bias={bias_c:+.2f}°C "
        f"({len(errors)} amostras, últimos {BIAS_WINDOW_DAYS}d)"
    )
    return round(bias_c, 3), len(errors)


def get_corrected_forecast(city_slug, forecast_day):
    """
    Retorna (forecast_c_corrigido, raw_sigma, bias_aplicado).
    forecast_c_corrigido = forecast_c_raw - bias
    """
    raw = get_forecast(city_slug, forecast_day)
    if raw is None or raw[0] is None:
        return None, None, 0.0

    forecast_c, raw_sigma = raw
    bias_c, n_samples = compute_bias(city_slug)

    corrected = round(float(forecast_c) - bias_c, 2)

    if bias_c != 0.0:
        print(
            f"[bias] {city_slug} d{forecast_day}: "
            f"{forecast_c:.1f}°C → {corrected:.1f}°C "
            f"(bias={bias_c:+.2f}°C, n={n_samples})"
        )

    return corrected, raw_sigma, bias_c


# =========================================================
# CACHE COM TTL
# =========================================================

_FORECAST_CACHE = {}
_CACHE_TIME     = {}

CACHE_TTL_SECONDS = 3600

# =========================================================
# FORECAST
# =========================================================

def get_forecast(city_slug, forecast_day=1):
    """
    Retorna (forecast_c, raw_sigma) sem correção de bias.
    Use get_corrected_forecast() em bot.py.

    forecast_day: 1 = HOJE (dia local da cidade), 2 = amanhã, ...
    Com timezone=auto, o índice 0 do array diário do Open-Meteo é o
    dia local de hoje na cidade — alinhado com a convenção acima.
    """
    cache_key = (city_slug, forecast_day)
    now       = time.time()

    if cache_key in _FORECAST_CACHE:
        age = now - _CACHE_TIME[cache_key]
        if age < CACHE_TTL_SECONDS:
            return _FORECAST_CACHE[cache_key]
        else:
            del _FORECAST_CACHE[cache_key]
            del _CACHE_TIME[cache_key]

    if city_slug not in CITY_COORDS:
        print(f"[forecast] cidade desconhecida: {city_slug}")
        return None, None

    lat, lon = CITY_COORDS[city_slug]

    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude":      lat,
        "longitude":     lon,
        "daily":         "temperature_2m_max",
        # CORRIGIDO: agregação diária no fuso LOCAL da cidade
        "timezone":      "auto",
        "forecast_days": 7,
    }

    try:
        r = requests.get(url, params=params, timeout=20)

        if r.status_code != 200:
            print(f"[forecast] erro status={r.status_code}")
            return None, None

        data = r.json()

        if (
            "daily" not in data
            or "temperature_2m_max" not in data["daily"]
        ):
            print("[forecast] resposta inválida")
            return None, None

        temps = data["daily"]["temperature_2m_max"]
        idx   = max(0, min(forecast_day - 1, len(temps) - 1))
        if temps[idx] is None:
            print(f"[forecast] valor ausente para {city_slug} d{forecast_day}")
            return None, None
        forecast_c = float(temps[idx])

        # Sigma base por horizonte (1 = hoje) + ajustes climáticos por cidade
        base_sigma_by_day = {1: 4.0, 2: 4.5, 3: 5.0, 4: 5.5, 5: 6.0}
        sigma = base_sigma_by_day.get(forecast_day, 6.0)

        if city_slug in ["hong-kong", "houston", "austin", "miami"]:
            sigma += 0.40
        if city_slug in ["denver", "seattle", "london", "boston"]:
            sigma += 0.30
        if city_slug == "chicago":
            sigma += 0.50

        sigma = round(sigma, 2)

        print(
            f"[forecast] {city_slug} "
            f"forecast={forecast_c:.1f}C sigma={sigma:.2f}"
        )

        result = (forecast_c, sigma)
        _FORECAST_CACHE[cache_key] = result
        _CACHE_TIME[cache_key]     = now

        return result

    except Exception as e:
        print(f"[forecast] erro: {e}")
        return None, None
