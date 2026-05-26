# =========================================================
# FORECAST ENGINE — OPEN METEO (COM TTL + BIAS CORRECTION)
#
# CORRIGIDO: sigma base aumentado de {1:2.0, 2:2.3, 3:2.6}
#   para {1:2.8, 2:3.2, 3:3.5} com base no erro real
#   observado nos 26 trades: média 2.5°C, máximo 5.3°C.
#   Sigma muito baixo cria falsa precisão e leva o modelo
#   a apostar em zonas de incerteza com confiança ilusória.
#
# MANTIDO: bias_correction() — ainda sem amostras suficientes
#   por cidade, mas a infraestrutura está pronta.
#
# MANTIDO: Toronto, Madrid, Mexico City.
# =========================================================

import requests
import time
from datetime import datetime, timezone, timedelta

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

    errors = []
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
                if exit_dt < cutoff:
                    continue
            except Exception:
                pass

        err = float(t["forecast_c"]) - float(t["real_temp_c"])
        errors.append(err)

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

    CORRIGIDO: sigma base aumentado para refletir erro real observado.
    Dados dos 26 trades: erro médio 2.5°C, máximo 5.3°C (Denver).
    Sigma de 2.0–2.6 era otimista demais — probabilidades ilusoriamente
    precisas faziam o modelo apostar onde não tinha convicção real.
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
        "timezone":      "UTC",
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
        forecast_c = float(temps[idx])

        # CORRIGIDO: sigma base calibrado pelo erro real observado.
        # Antes: {1:2.0, 2:2.3, 3:2.6} — subestimava incerteza real.
        # Agora: {1:2.8, 2:3.2, 3:3.5} — alinhado com dados reais.
        base_sigma_by_day = {1: 2.8, 2: 3.2, 3: 3.5, 4: 4.0, 5: 4.5}
        sigma = base_sigma_by_day.get(forecast_day, 4.5)

        # Ajustes climáticos por cidade (variabilidade extra conhecida)
        if city_slug in ["hong-kong", "houston", "austin", "miami"]:
            sigma += 0.30
        if city_slug in ["denver", "seattle", "london", "boston"]:
            sigma += 0.20
        if city_slug == "chicago":
            sigma += 0.40

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
