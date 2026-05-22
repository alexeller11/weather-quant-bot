# =========================================================
# FORECAST ENGINE — OPEN METEO
# =========================================================

import requests

# =========================================================
# COORDENADAS
# =========================================================

CITY_COORDS = {

    "new-york": (40.7128, -74.0060),
    "london": (51.5072, -0.1276),
    "paris": (48.8566, 2.3522),
    "hong-kong": (22.3193, 114.1694),
    "tokyo": (35.6762, 139.6503),
    "seoul": (37.5665, 126.9780),
    "beijing": (39.9042, 116.4074),
    "sao-paulo": (-23.5505, -46.6333),
}

# =========================================================
# FORECAST
# =========================================================

def get_forecast(city_slug, forecast_day=1):

    if city_slug not in CITY_COORDS:

        print(
            f"[forecast] cidade desconhecida: "
            f"{city_slug}"
        )

        return None, None

    lat, lon = CITY_COORDS[city_slug]

    url = (
        "https://api.open-meteo.com/v1/forecast"
    )

    params = {

        "latitude": lat,

        "longitude": lon,

        "daily": "temperature_2m_max",

        "timezone": "UTC",

        "forecast_days": 7,
    }

    try:

        r = requests.get(
            url,
            params=params,
            timeout=20,
        )

        data = r.json()

        temps = data["daily"][
            "temperature_2m_max"
        ]

        idx = max(
            0,
            min(forecast_day - 1, len(temps)-1)
        )

        forecast_c = float(temps[idx])

        # =====================================
        # SIGMA SIMPLES
        # =====================================

        sigma = 2.5 + (forecast_day * 0.4)

        return forecast_c, sigma

    except Exception as e:

        print(f"[forecast] erro: {e}")

        return None, None
