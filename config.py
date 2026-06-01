#!/usr/bin/env python3
"""
Configurações do Weather Quant Bot v3.
Arquivo unificado com TODAS as constantes necessárias para o projeto.

CORRIGIDO:
- TRADING_ENABLED padrão era 1 (ligado) — corrigido para 0 (modo observação)
- Adicionadas constantes ausentes: SIGMA_MAX_ABOVE_BELOW, MIN_EV, EDGE_THRESHOLD,
  CITY_SLUGS, MAX_FORECAST_DAY, MIN_EV
- PROBABILITY_DEAD_ZONE_LOW/HIGH adicionados como aliases de PROB_DEADZONE_MIN/MAX
  para compatibilidade com audit_model.py e check_version.py
- START_BALANCE padrão padronizado para 100.00 (era 1000 em reset_bankroll.py)
"""

import os
import json

# ============================================================
# Configurações de Risco
# ============================================================

# CORRIGIDO: padrão era "1" — deve ser "0" (modo observação por segurança)
TRADING_ENABLED = int(os.getenv("TRADING_ENABLED", "0"))

# Recalibrado após simulação (jun/2026): win rate real 23% vs 70%+ previsto.
# Eleva thresholds para só entrar em trades onde o modelo é genuinamente confiante.
MIN_PROB_ABOVE_BELOW = float(os.getenv("MIN_PROB_ABOVE_BELOW", "0.80"))
MIN_TARGET_ZSCORE = float(os.getenv("MIN_TARGET_ZSCORE", "2.00"))
MAX_POSITION = float(os.getenv("MAX_POSITION", "2.00"))
MAX_TOTAL_EXPOSURE = float(os.getenv("MAX_TOTAL_EXPOSURE", "8.00"))
MAX_OPEN_TRADES = int(os.getenv("MAX_OPEN_TRADES", "4"))
KELLY_FRACTION = float(os.getenv("KELLY_FRACTION", "0.50"))
MAX_KELLY_FRACTION_CAP = float(os.getenv("MAX_KELLY_FRACTION_CAP", "0.50"))

# Edge mínimo
MIN_EDGE = float(os.getenv("MIN_EDGE", "0.02"))
# EXACT win rate observado: 16.7% — eleva edge mínimo para compensar.
MIN_EDGE_EXACT = float(os.getenv("MIN_EDGE_EXACT", "0.15"))

# ADICIONADO: MIN_EV ausente (usado em check_version.py e risk.py)
MIN_EV = float(os.getenv("MIN_EV", "0.05"))

# ADICIONADO: EDGE_THRESHOLD como alias de MIN_EDGE (usado em teste.py)
EDGE_THRESHOLD = MIN_EDGE

# ADICIONADO: MAX_FORECAST_DAY (usado em teste.py)
MAX_FORECAST_DAY = int(os.getenv("MAX_FORECAST_DAY", "3"))

# Sigma caps
SIGMA_CAP_ABOVE_BELOW = float(os.getenv("SIGMA_CAP_ABOVE_BELOW", "6.0"))
SIGMA_CAP_EXACT = float(os.getenv("SIGMA_CAP_EXACT", "6.0"))

# ADICIONADO: SIGMA_MAX_ABOVE_BELOW como alias de SIGMA_CAP_ABOVE_BELOW
# (usado em check_version.py e audit_model.py)
SIGMA_MAX_ABOVE_BELOW = SIGMA_CAP_ABOVE_BELOW

# Zona morta de probabilidade
PROB_DEADZONE_MIN = float(os.getenv("PROB_DEADZONE_MIN", "0.45"))
PROB_DEADZONE_MAX = float(os.getenv("PROB_DEADZONE_MAX", "0.55"))

# ADICIONADO: aliases para compatibilidade com audit_model.py
PROBABILITY_DEAD_ZONE_LOW = PROB_DEADZONE_MIN
PROBABILITY_DEAD_ZONE_HIGH = PROB_DEADZONE_MAX

# Liquidez
MIN_PRICE = float(os.getenv("MIN_PRICE", "0.12"))
MAX_PRICE = float(os.getenv("MAX_PRICE", "0.88"))

# ============================================================
# Bankroll
# ============================================================

# CORRIGIDO: padronizado para 100.00 em todos os lugares
START_BALANCE = float(os.getenv("START_BALANCE", "100.00"))

CITY_DISPLAY = {
    "new york":    "New York",
    "london":      "London",
    "paris":       "Paris",
    "hong kong":   "Hong Kong",
    "tokyo":       "Tokyo",
    "seoul":       "Seoul",
    "beijing":     "Beijing",
    "sao paulo":   "São Paulo",
    "milan":       "Milan",
    "los angeles": "Los Angeles",
    "houston":     "Houston",
    "austin":      "Austin",
    "denver":      "Denver",
    "seattle":     "Seattle",
    "chicago":     "Chicago",
    "phoenix":     "Phoenix",
    "miami":       "Miami",
    "atlanta":     "Atlanta",
    "boston":      "Boston",
    "toronto":     "Toronto",
    "madrid":      "Madrid",
    "mexico city": "Mexico City",
}

CITY_SLUG_NORMALIZE = {
    "new-york":      "new york",
    "new york city": "new york",
    "nyc":           "new york",
    "london":        "london",
    "paris":         "paris",
    "hong-kong":     "hong kong",
    "hong kong":     "hong kong",
    "tokyo":         "tokyo",
    "seoul":         "seoul",
    "beijing":       "beijing",
    "sao-paulo":     "sao paulo",
    "são paulo":     "sao paulo",
    "milan":         "milan",
    "los-angeles":   "los angeles",
    "los angeles":   "los angeles",
    "houston":       "houston",
    "austin":        "austin",
    "denver":        "denver",
    "seattle":       "seattle",
    "chicago":       "chicago",
    "phoenix":       "phoenix",
    "miami":         "miami",
    "atlanta":       "atlanta",
    "boston":        "boston",
    "toronto":       "toronto",
    "madrid":        "madrid",
    "mexico-city":   "mexico city",
    "mexico city":   "mexico city",
}

# ============================================================
# Carregamento de Cidades
# ============================================================

# ADICIONADO: CITY_SLUGS para compatibilidade com teste.py e outros scripts
CITY_SLUGS = [
    "new-york", "london", "paris", "hong-kong", "tokyo", "seoul",
    "beijing", "sao-paulo", "milan", "los-angeles", "houston", "austin",
    "denver", "seattle", "chicago", "phoenix", "miami", "atlanta",
    "boston", "toronto", "madrid", "mexico-city",
]

_CITIES_FALLBACK = [
    {"name": "New York",     "lat": 40.7128,  "lon": -74.0060},
    {"name": "London",       "lat": 51.5074,  "lon": -0.1278},
    {"name": "Paris",        "lat": 48.8566,  "lon":  2.3522},
    {"name": "Hong Kong",    "lat": 22.3193,  "lon": 114.1694},
    {"name": "Tokyo",        "lat": 35.6762,  "lon": 139.6503},
    {"name": "Seoul",        "lat": 37.5665,  "lon": 126.9780},
    {"name": "Beijing",      "lat": 39.9042,  "lon": 116.4074},
    {"name": "São Paulo",    "lat": -23.5505, "lon": -46.6333},
    {"name": "Milan",        "lat": 45.4642,  "lon":   9.1900},
    {"name": "Los Angeles",  "lat": 34.0522,  "lon": -118.2437},
    {"name": "Houston",      "lat": 29.7604,  "lon": -95.3698},
    {"name": "Austin",       "lat": 30.2672,  "lon": -97.7431},
    {"name": "Denver",       "lat": 39.7392,  "lon": -104.9903},
    {"name": "Seattle",      "lat": 47.6062,  "lon": -122.3321},
    {"name": "Chicago",      "lat": 41.8781,  "lon": -87.6298},
    {"name": "Phoenix",      "lat": 33.4484,  "lon": -112.0740},
    {"name": "Miami",        "lat": 25.7617,  "lon": -80.1918},
    {"name": "Atlanta",      "lat": 33.7490,  "lon": -84.3880},
    {"name": "Boston",       "lat": 42.3601,  "lon": -71.0589},
    {"name": "Toronto",      "lat": 43.6532,  "lon": -79.3832},
    {"name": "Madrid",       "lat": 40.4168,  "lon":  -3.7038},
    {"name": "Mexico City",  "lat": 19.4326,  "lon": -99.1332},
]


def load_cities():
    """Carrega a lista de cidades de cities.json, com fallback embutido."""
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

# ============================================================
# Configurações de API
# ============================================================

TELEGRAM_TOKEN  = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID         = os.getenv("CHAT_ID", "")
GITHUB_TOKEN    = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO     = os.getenv("GITHUB_REPO", "")
GITHUB_BRANCH   = os.getenv("GITHUB_BRANCH", "main")
GROQ_API_KEY    = os.getenv("GROQ_API_KEY", "")
DATABASE_URL    = os.getenv("DATABASE_URL", "")
WEATHERAPI_KEY  = os.getenv("WEATHERAPI_KEY", "")

# ============================================================
# Logging
# ============================================================

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
