import requests
import statistics
from statistics import NormalDist
import math
from config import CITY_MIN_SIGMA, CITY_COORDS_BY_SLUG

# ── Sigma fallback por horizonte de previsão ──────────────────────────────────
SIGMA_BY_DAY = {0: 2.0, 1: 2.5, 2: 3.8, 3: 5.0}
DEFAULT_SIGMA = 5.0

# ── Inflation do sigma do ensemble ───────────────────────────────────────────
SIGMA_ENSEMBLE_INFLATION = {0: 1.0, 1: 1.2, 2: 1.6, 3: 2.1}
DEFAULT_INFLATION = 2.5

# ── Sigma climatológico por cidade (RMSE histórico de previsão D+1) ──────────
SIGMA_CLIMATOLOGICO = {
    "seoul":        2.2,
    "tokyo":        1.7,
    "beijing":      2.5,
    "hong-kong":    1.5,
    "paris":        1.8,
    "london":       1.8,
    "milan":        1.9,
    "madrid":       2.1,
    "berlin":       2.0,
    "amsterdam":    1.9,
    "new-york":     2.3,
    "los-angeles":  1.6,
    "chicago":      2.6,
    "toronto":      2.4,
    "mexico-city":  2.0,
    "sao-paulo":    1.6,
    "buenos-aires": 1.8,
    "austin":       2.3,
}
SIGMA_CLIM_DEFAULT = 2.0

# ── Sigma mínimo absoluto para EXACT ─────────────────────────────────────────
# Com janela ±0.5°C, sigma < 2.5°C gera probabilidades irrealisticamente altas.
# P(X=24±0.5 | μ=24, σ=1) ≈ 38% — impossível na prática.
# P(X=24±0.5 | μ=24, σ=2.5) ≈ 15.8% — realista.
SIGMA_MIN_EXACT = 2.5


def to_celsius(value, unit):
    """Converte target para °C se necessário."""
    if str(unit).upper() == "F":
        return (float(value) - 32.0) * 5.0 / 9.0
    return float(value)


def get_sigma_fallback(forecast_day):
    return SIGMA_BY_DAY.get(forecast_day, DEFAULT_SIGMA)


def get_forecast_ensemble(city_slug, forecast_day=1):
    """
    Retorna (mean_c, sigma_c) via ensemble de 50 membros da Open-Meteo.
    timezone=UTC fixo para evitar problemas de fuso em cidades UTC+N.
    Retorna (None, None) em caso de erro.
    """
    if city_slug not in CITY_COORDS_BY_SLUG:
        return None, None

    lat, lon = CITY_COORDS_BY_SLUG[city_slug]

    url = (
        "https://ensemble-api.open-meteo.com/v1/ensemble"
        f"?latitude={lat}"
        f"&longitude={lon}"
        "&models=icon_seamless"
        "&daily=temperature_2m_max"
        f"&forecast_days={max(forecast_day + 1, 3)}"
        "&timezone=UTC"
    )

    try:
        r    = requests.get(url, timeout=15)
        data = r.json()
        daily = data.get("daily", {})

        member_values = []
        for key, values in daily.items():
            if "temperature_2m_max" in key and "member" in key:
                if isinstance(values, list) and forecast_day < len(values):
                    val = values[forecast_day]
                    if val is not None:
                        member_values.append(float(val))

        if len(member_values) < 5:
            return None, None

        mean      = statistics.mean(member_values)
        raw_sigma = statistics.stdev(member_values)
        sigma     = max(raw_sigma, 0.3)
        print(f"  [Ensemble debug] {city_slug} day={forecast_day}: "
              f"{len(member_values)} membros, raw_sigma={raw_sigma:.2f}°C sigma_used={sigma:.2f}°C")
        return round(mean, 2), round(sigma, 2)

    except Exception as e:
        print(f"Erro ensemble {city_slug}: {e}")
        return None, None


def get_forecast_simple(city_slug, forecast_day=1):
    """
    Temperatura máxima prevista (°C) via forecast padrão.
    Fallback quando o ensemble não responde.
    """
    if city_slug not in CITY_COORDS_BY_SLUG:
        return None

    lat, lon = CITY_COORDS_BY_SLUG[city_slug]

    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}"
        f"&longitude={lon}"
        "&daily=temperature_2m_max"
        f"&forecast_days={max(forecast_day + 1, 3)}"
        "&timezone=UTC"
    )

    try:
        r    = requests.get(url, timeout=10)
        data = r.json()
        temps = data["daily"]["temperature_2m_max"]

        if forecast_day >= len(temps):
            return float(temps[-1])
        return float(temps[forecast_day])

    except Exception as e:
        print(f"Erro forecast simples {city_slug}: {e}")
        return None


def calculate_probability(city, target, unit="C", forecast_day=1,
                          condition="above", target_high=None):
    """
    Calcula P(temperatura satisfaz condição) via modelo Normal.

    Suporta quatro condições:
      'above'  → P(temp >= target)
      'below'  → P(temp <= target)
      'exact'  → P(target-0.5 < temp <= target+0.5)
      'range'  → P(target_low <= temp <= target_high)

    FIX: Para EXACT, sigma_total nunca fica abaixo de SIGMA_MIN_EXACT (2.5°C).
         Isso evita probabilidades infladas (30-70%) que causavam edge falso.
         Com sigma correto, EXACT raramente passa de 15-20% — realista.
    """
    target_c = to_celsius(target, unit)

    forecast_c, sigma = get_forecast_ensemble(city, forecast_day)

    if forecast_c is not None and sigma is not None:
        # 1. Infla sigma do ensemble por horizonte
        raw_sigma = sigma
        inflation = SIGMA_ENSEMBLE_INFLATION.get(forecast_day, DEFAULT_INFLATION)
        sigma_ens = round(sigma * inflation, 2)

        # 2. Combina com sigma climatológico via soma quadrática
        city_slug  = city.lower().replace(" ", "-")
        sigma_clim = SIGMA_CLIMATOLOGICO.get(city_slug, SIGMA_CLIM_DEFAULT)
        sigma      = round(math.sqrt(sigma_ens**2 + sigma_clim**2), 2)

        # 3. FIX — Aplica sigma mínimo por cidade (config.CITY_MIN_SIGMA)
        city_min = CITY_MIN_SIGMA.get(city_slug, 0.0)
        if sigma < city_min:
            print(f"  [sigma] {city}: sigma {sigma:.2f} → {city_min:.2f} (city_min)")
            sigma = city_min

        # 4. FIX — Para EXACT: sigma mínimo absoluto realista (SIGMA_MIN_EXACT)
        #    Janela ±0.5°C com sigma < 2.5 gera probabilidades impossíveis.
        if condition == "exact" and sigma < SIGMA_MIN_EXACT:
            print(f"  [sigma] {city} EXACT: sigma {sigma:.2f} → {SIGMA_MIN_EXACT:.2f} (min_exact)")
            sigma = SIGMA_MIN_EXACT

        print(f"  [Ensemble] {city} day={forecast_day}: "
              f"mean={forecast_c:.1f}°C σ_raw={raw_sigma:.2f} σ_ens={sigma_ens:.2f} "
              f"σ_clim={sigma_clim:.2f} σ_total={sigma:.2f}°C")
    else:
        forecast_c = get_forecast_simple(city, forecast_day)
        if forecast_c is None:
            print(f"  Sem forecast para {city}, usando prob neutra 0.50")
            return 0.50
        sigma = get_sigma_fallback(forecast_day)

        # FIX — aplica mínimo mesmo no fallback
        city_slug = city.lower().replace(" ", "-")
        city_min  = CITY_MIN_SIGMA.get(city_slug, 0.0)
        sigma     = max(sigma, city_min)
        if condition == "exact":
            sigma = max(sigma, SIGMA_MIN_EXACT)

        print(f"  [Simples] {city} day={forecast_day}: "
              f"mean={forecast_c:.1f}°C sigma={sigma:.2f}°C (fallback)")

    dist = NormalDist(mu=forecast_c, sigma=sigma)

    if condition == "above":
        prob = 1.0 - dist.cdf(target_c)

    elif condition == "below":
        prob = dist.cdf(target_c)

    elif condition == "exact":
        # P(target - 0.5 < temp <= target + 0.5)
        half_window_c = 0.5 if unit.upper() == "C" else (0.5 * 5.0 / 9.0)
        prob = dist.cdf(target_c + half_window_c) - dist.cdf(target_c - half_window_c)

    elif condition == "range" and target_high is not None:
        target_high_c = to_celsius(target_high, unit)
        prob = dist.cdf(target_high_c) - dist.cdf(target_c)
        if prob < 0:
            prob = 0.0

    else:
        print(f"  Condição desconhecida: '{condition}'. Usando 0.50.")
        prob = 0.50

    return round(max(0.01, min(prob, 0.99)), 4)
