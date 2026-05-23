# =========================================================
# FORECAST ENGINE — OPEN METEO (COM TTL)
# FIX: Toronto, Madrid, Mexico City adicionados a CITY_COORDS
#      Sem isso, get_forecast() retornava None para essas cidades
#      e o bot nunca abria trades nelas.
# =========================================================

import requests
import time

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

    # FIX: cidades ausentes — bot retornava None para estas
    "toronto":     (43.6532, -79.3832),
    "madrid":      (40.4168, -3.7038),
    "mexico-city": (19.4326, -99.1332),
}

# =========================================================
# CACHE COM TTL
# =========================================================

_FORECAST_CACHE = {}
_CACHE_TIME     = {}

CACHE_TTL_SECONDS = 3600  # 1 hora

# =========================================================
# FORECAST
# =========================================================

def get_forecast(
    city_slug,
    forecast_day=1,
):

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
        print(
            f"[forecast] cidade desconhecida: "
            f"{city_slug}"
        )
        return None, None

    lat, lon = CITY_COORDS[city_slug]

    url = "https://api.open-meteo.com/v1/forecast"

    params = {
        "latitude":     lat,
        "longitude":    lon,
        "daily":        "temperature_2m_max",
        "timezone":     "UTC",
        "forecast_days": 7,
    }

    try:

        r = requests.get(
            url,
            params=params,
            timeout=20,
        )

        if r.status_code != 200:
            print(
                f"[forecast] erro status="
                f"{r.status_code}"
            )
            return None, None

        data = r.json()

        if (
            "daily" not in data
            or "temperature_2m_max" not in data["daily"]
        ):
            print("[forecast] resposta inválida")
            return None, None

        temps = data["daily"]["temperature_2m_max"]

        idx = max(
            0,
            min(forecast_day - 1, len(temps) - 1)
        )

        forecast_c = float(temps[idx])

        # =====================================================
        # SIGMA BASE
        # =====================================================

        base_sigma = 2.2
        sigma = base_sigma + (forecast_day * 0.7)

        # Ajustes climáticos
        if city_slug in ["hong-kong", "houston", "austin", "miami"]:
            sigma += 0.4

        if city_slug in ["denver", "seattle", "london", "boston"]:
            sigma += 0.2

        if city_slug == "chicago":
            sigma += 0.6

        sigma = round(sigma, 2)

        print(
            f"[forecast] "
            f"{city_slug} "
            f"forecast={forecast_c:.1f}C "
            f"sigma={sigma:.2f}"
        )

        result = (forecast_c, sigma)

        _FORECAST_CACHE[cache_key] = result
        _CACHE_TIME[cache_key]     = now

        return result

    except Exception as e:
        print(f"[forecast] erro: {e}")
        return None, None
