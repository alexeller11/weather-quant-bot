#!/usr/bin/env python3
"""
config.py — Configurações do Weather Quant Bot v5.1

AJUSTES v5.1 baseados nos logs reais de 2026-06-01:
- MIN_PROB_ABOVE_BELOW: 0.80 → 0.72
  Tokyo ABOVE 27°C com prob=0.766 e edge=+0.647 estava sendo bloqueado.
  Com sigma=4.0, prob=0.77 exige forecast ~3°C acima do target — convicção real.

- MIN_PRICE geral: 0.10 → 0.08
  Houston ABOVE 92°F a 0.095 bloqueado por 0.5 centavo.
  Mercados legítimos com liquidez real ficam entre 0.08 e 0.10.

- MIN_PRICE_RANGE2: novo parâmetro separado = 0.04
  Buckets raros de range2 (ex: Atlanta 86.5°F a 0.034) têm preço baixo
  por natureza — não por iliquidez. Precisa de piso menor.

- MAX_EDGE_RANGE2: novo parâmetro = 0.25
  Milan ABOVE 24°C com edge=0.848 foi bloqueado pelo cap de 0.40 (correto).
  Para RANGE2 o edge máximo pode ser menor (0.25) pois probs são mais baixas.
"""

import os
import json

TRADING_ENABLED       = int(os.getenv("TRADING_ENABLED", "0"))

# AJUSTADO: 0.80 → 0.72
# Tokyo prob=0.766 com edge=+0.647 era trade válido sendo bloqueado
MIN_PROB_ABOVE_BELOW  = float(os.getenv("MIN_PROB_ABOVE_BELOW", "0.72"))

MIN_TARGET_ZSCORE     = float(os.getenv("MIN_TARGET_ZSCORE", "1.00"))
MAX_POSITION          = float(os.getenv("MAX_POSITION", "4.00"))
MAX_TOTAL_EXPOSURE    = float(os.getenv("MAX_TOTAL_EXPOSURE", "20.00"))
MAX_OPEN_TRADES       = int(os.getenv("MAX_OPEN_TRADES", "5"))
KELLY_FRACTION        = float(os.getenv("KELLY_FRACTION", "0.50"))
MAX_KELLY_FRACTION_CAP= float(os.getenv("MAX_KELLY_FRACTION_CAP", "0.50"))
MIN_EDGE              = float(os.getenv("MIN_EDGE", "0.02"))
MIN_EDGE_EXACT        = float(os.getenv("MIN_EDGE_EXACT", "0.15"))
MIN_EV                = float(os.getenv("MIN_EV", "0.05"))
EDGE_THRESHOLD        = MIN_EDGE
MAX_FORECAST_DAY      = int(os.getenv("MAX_FORECAST_DAY", "3"))
SIGMA_CAP_ABOVE_BELOW = float(os.getenv("SIGMA_CAP_ABOVE_BELOW", "6.0"))
SIGMA_CAP_EXACT       = float(os.getenv("SIGMA_CAP_EXACT", "6.0"))
SIGMA_MAX_ABOVE_BELOW = SIGMA_CAP_ABOVE_BELOW
PROB_DEADZONE_MIN     = float(os.getenv("PROB_DEADZONE_MIN", "0.45"))
PROB_DEADZONE_MAX     = float(os.getenv("PROB_DEADZONE_MAX", "0.55"))
PROBABILITY_DEAD_ZONE_LOW  = PROB_DEADZONE_MIN
PROBABILITY_DEAD_ZONE_HIGH = PROB_DEADZONE_MAX

# AJUSTADO v5.5: 0.08 → 0.15 para YES
# Seoul a 0.09 gerou retorno de 39x distorcendo paper trading.
# Preços abaixo de 0.15 indicam mercado ilíquido ou já "decidido".
MIN_PRICE             = float(os.getenv("MIN_PRICE", "0.15"))

# NOVO: piso separado para RANGE2 — buckets raros têm preço baixo por natureza
MIN_PRICE_RANGE2      = float(os.getenv("MIN_PRICE_RANGE2", "0.04"))

MAX_PRICE             = float(os.getenv("MAX_PRICE", "0.88"))
START_BALANCE         = float(os.getenv("START_BALANCE", "100.00"))

CITY_DISPLAY = {
    "new york":    "New York",   "london":      "London",
    "paris":       "Paris",      "hong kong":   "Hong Kong",
    "tokyo":       "Tokyo",      "seoul":       "Seoul",
    "beijing":     "Beijing",    "sao paulo":   "São Paulo",
    "milan":       "Milan",      "los angeles": "Los Angeles",
    "houston":     "Houston",    "austin":      "Austin",
    "denver":      "Denver",     "seattle":     "Seattle",
    "chicago":     "Chicago",    "phoenix":     "Phoenix",
    "miami":       "Miami",      "atlanta":     "Atlanta",
    "boston":      "Boston",     "toronto":     "Toronto",
    "madrid":      "Madrid",     "mexico city": "Mexico City",
}

CITY_SLUG_NORMALIZE = {
    "new-york": "new york", "new york city": "new york", "nyc": "new york",
    "london": "london", "paris": "paris",
    "hong-kong": "hong kong", "hong kong": "hong kong",
    "tokyo": "tokyo", "seoul": "seoul", "beijing": "beijing",
    "sao-paulo": "sao paulo", "são paulo": "sao paulo",
    "milan": "milan", "los-angeles": "los angeles", "los angeles": "los angeles",
    "houston": "houston", "austin": "austin", "denver": "denver",
    "seattle": "seattle", "chicago": "chicago", "phoenix": "phoenix",
    "miami": "miami", "atlanta": "atlanta", "boston": "boston",
    "toronto": "toronto", "madrid": "madrid",
    "mexico-city": "mexico city", "mexico city": "mexico city",
}

CITY_SLUGS = [
    "new-york", "london", "paris", "hong-kong", "tokyo", "seoul",
    "beijing", "sao-paulo", "milan", "los-angeles", "houston", "austin",
    "denver", "seattle", "chicago", "phoenix", "miami", "atlanta",
    "boston", "toronto", "madrid", "mexico-city",
]

_CITIES_FALLBACK = [
    {"name": "New York",    "lat": 40.7128,  "lon": -74.0060},
    {"name": "London",      "lat": 51.5074,  "lon": -0.1278},
    {"name": "Paris",       "lat": 48.8566,  "lon":  2.3522},
    {"name": "Hong Kong",   "lat": 22.3193,  "lon": 114.1694},
    {"name": "Tokyo",       "lat": 35.6762,  "lon": 139.6503},
    {"name": "Seoul",       "lat": 37.5665,  "lon": 126.9780},
    {"name": "Beijing",     "lat": 39.9042,  "lon": 116.4074},
    {"name": "São Paulo",   "lat": -23.5505, "lon": -46.6333},
    {"name": "Milan",       "lat": 45.4642,  "lon":   9.1900},
    {"name": "Los Angeles", "lat": 34.0522,  "lon": -118.2437},
    {"name": "Houston",     "lat": 29.7604,  "lon": -95.3698},
    {"name": "Austin",      "lat": 30.2672,  "lon": -97.7431},
    {"name": "Denver",      "lat": 39.7392,  "lon": -104.9903},
    {"name": "Seattle",     "lat": 47.6062,  "lon": -122.3321},
    {"name": "Chicago",     "lat": 41.8781,  "lon": -87.6298},
    {"name": "Phoenix",     "lat": 33.4484,  "lon": -112.0740},
    {"name": "Miami",       "lat": 25.7617,  "lon": -80.1918},
    {"name": "Atlanta",     "lat": 33.7490,  "lon": -84.3880},
    {"name": "Boston",      "lat": 42.3601,  "lon": -71.0589},
    {"name": "Toronto",     "lat": 43.6532,  "lon": -79.3832},
    {"name": "Madrid",      "lat": 40.4168,  "lon":  -3.7038},
    {"name": "Mexico City", "lat": 19.4326,  "lon": -99.1332},
]


def load_cities():
    cities_path = os.path.join(os.path.dirname(__file__), "cities.json")
    try:
        with open(cities_path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return _CITIES_FALLBACK
    except Exception as e:
        print(f"ERRO ao carregar cidades: {e}")
        return _CITIES_FALLBACK


CITIES = load_cities()

TELEGRAM_TOKEN  = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID         = os.getenv("CHAT_ID", "")
GITHUB_TOKEN    = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO     = os.getenv("GITHUB_REPO", "")
GITHUB_BRANCH   = os.getenv("GITHUB_BRANCH", "main")
GROQ_API_KEY    = os.getenv("GROQ_API_KEY", "")
DATABASE_URL    = os.getenv("DATABASE_URL", "")
WEATHERAPI_KEY  = os.getenv("WEATHERAPI_KEY", "")
LOG_LEVEL       = os.getenv("LOG_LEVEL", "INFO")
