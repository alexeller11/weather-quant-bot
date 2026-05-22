import requests
import statistics
from statistics import NormalDist
from config import CITY_MIN_SIGMA

from config import CITY_COORDS_BY_SLUG

# ── Sigma fallback por horizonte de previsão ──────────────────────────────────
SIGMA_BY_DAY = {0: 2.0, 1: 2.5, 2: 3.8, 3: 5.0}
DEFAULT_SIGMA = 5.0

# ── Inflation de incerteza aplicado ao sigma do ensemble ─────────────────────
# O ensemble subestima a incerteza real em horizontes maiores porque não captura
# eventos de mesoescala (frentes frias, brisas costeiras, convecção local).
# Multiplica o sigma bruto do ensemble por esses fatores antes de calcular a CDF.
# D+0: confiança alta — sem inflation
# D+1: pequena margem para erros de fase
# D+2: frentes podem chegar ±12h antes/depois, erro de 2-4°C comum
# D+3+: incerteza sinótica plena
SIGMA_ENSEMBLE_INFLATION = {0: 1.0, 1: 1.2, 2: 1.6, 3: 2.1}
DEFAULT_INFLATION = 2.5

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

        mean  = statistics.mean(member_values)
        raw_sigma = statistics.stdev(member_values)
        sigma     = max(raw_sigma, 0.3)   # floor 0.3°C — evita distribuições excessivamente estreitas
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
      'exact'  → P(temp == target) ≈ P(target-0.5 < temp <= target+0.5)
      'range'  → P(target_low <= temp <= target_high)
                 Requer target_high.

    Tenta ensemble primeiro (sigma real). Fallback: forecast simples
    + sigma hardcoded por horizonte.

    Returns:
        float: probabilidade entre 0.01 e 0.99
    """
    target_c = to_celsius(target, unit)

    forecast_c, sigma = get_forecast_ensemble(city, forecast_day)

    if forecast_c is not None and sigma is not None:
        # Aplica inflation de incerteza por horizonte de previsão.
        raw_sigma = sigma
        inflation = SIGMA_ENSEMBLE_INFLATION.get(forecast_day, DEFAULT_INFLATION)
        sigma = round(sigma * inflation, 2)

        # Sigma mínimo por condição:
        # EXACT exige sigma alto porque o ensemble subestima muito a incerteza
        # real de acertar um bucket de 1°C. RMSE real de D+1 é 2-3°C — para
        # bucket ±0.5°C isso implica sigma efetivo de 4-5°C.
        # ABOVE/BELOW: sigma mínimo mais baixo pois são apostas direcionais.
        if condition == "exact":
            SIGMA_MIN_EXACT = {0: 3.0, 1: 4.0, 2: 5.0, 3: 6.0}
            sigma_floor = SIGMA_MIN_EXACT.get(forecast_day, 6.0)
        elif condition in ("above", "below"):
            SIGMA_MIN_DIR = {0: 1.5, 1: 2.0, 2: 3.0, 3: 4.0}
            sigma_floor = SIGMA_MIN_DIR.get(forecast_day, 4.0)
        else:
            sigma_floor = 2.0

        if sigma < sigma_floor:
            print(f"  [SigmaFloor] {city} {condition}: sigma {sigma:.2f}→{sigma_floor:.2f}°C (floor D+{forecast_day})")
            sigma = sigma_floor

        # Aplica sigma mínimo adicional por cidade (configurável em config.py)
        city_slug = city.lower().replace(" ", "-")
        min_sigma = CITY_MIN_SIGMA.get(city_slug, 0.0)
        if sigma < min_sigma:
            sigma = min_sigma
            print(f"  [SigmaFloor] {city}: sigma aumentado para {sigma:.2f}°C (mínimo da cidade)")

        print(f"  [Ensemble] {city} day={forecast_day}: "
              f"mean={forecast_c:.1f}°C sigma_raw={raw_sigma:.2f}°C "
              f"sigma_inflated={sigma:.2f}°C (x{inflation})")
    else:
        forecast_c = get_forecast_simple(city, forecast_day)
        if forecast_c is None:
            print(f"  Sem forecast para {city}, usando prob neutra 0.50")
            return 0.50
        sigma = get_sigma_fallback(forecast_day)
        print(f"  [Simples] {city} day={forecast_day}: "
              f"mean={forecast_c:.1f}°C sigma={sigma:.2f}°C (fallback)")

    dist = NormalDist(mu=forecast_c, sigma=sigma)

    if condition == "above":
        # P(temp >= target)
        prob = 1.0 - dist.cdf(target_c)

    elif condition == "below":
        # P(temp <= target)
        prob = dist.cdf(target_c)

    elif condition == "exact":
        # P(target - 0.5 < temp <= target + 0.5)
        # Janela de ±0.5°C (ou ±1°F convertido a °C) em torno do valor exato
        half_window = 0.5 if unit.upper() == "C" else to_celsius(0.5, "delta_F")
        # Para delta Fahrenheit: ΔF * 5/9 = ΔC
        half_window_c = 0.5 if unit.upper() == "C" else (0.5 * 5.0 / 9.0)
        prob = dist.cdf(target_c + half_window_c) - dist.cdf(target_c - half_window_c)

    elif condition == "range" and target_high is not None:
        # P(target_low <= temp <= target_high)
        target_high_c = to_celsius(target_high, unit)
        prob = dist.cdf(target_high_c) - dist.cdf(target_c)
        # Garante que os limites estão na ordem certa
        if prob < 0:
            prob = 0.0

    else:
        print(f"  Condição desconhecida: '{condition}'. Usando 0.50.")
        prob = 0.50

    return round(max(0.01, min(prob, 0.99)), 4)
