#!/usr/bin/env python3
"""
Configurações do Weather Quant Bot v3.
Arquivo unificado com TODAS as constantes necessárias para o projeto.
"""

import os
import json

# ============================================================
# Configurações de Risco
# ============================================================

TRADING_ENABLED = int(os.getenv("TRADING_ENABLED", "1"))
MIN_PROB_ABOVE_BELOW = float(os.getenv("MIN_PROB_ABOVE_BELOW", "0.70"))
MIN_TARGET_ZSCORE = float(os.getenv("MIN_TARGET_ZSCORE", "1.50"))
MAX_POSITION = float(os.getenv("MAX_POSITION", "2.00"))
MAX_TOTAL_EXPOSURE = float(os.getenv("MAX_TOTAL_EXPOSURE", "8.00"))
MAX_OPEN_TRADES = int(os.getenv("MAX_OPEN_TRADES", "4"))
KELLY_FRACTION = float(os.getenv("KELLY_FRACTION", "0.50"))
MAX_KELLY_FRACTION_CAP = float(os.getenv("MAX_KELLY_FRACTION_CAP", "0.50"))

# Sigma caps
SIGMA_CAP_ABOVE_BELOW = float(os.getenv("SIGMA_CAP_ABOVE_BELOW", "3.6"))
SIGMA_CAP_EXACT = float(os.getenv("SIGMA_CAP_EXACT", "4.0"))

# Zona morta de probabilidade
PROB_DEADZONE_MIN = float(os.getenv("PROB_DEADZONE_MIN", "0.45"))
PROB_DEADZONE_MAX = float(os.getenv("PROB_DEADZONE_MAX", "0.55"))

# Liquidez
MIN_PRICE = float(os.getenv("MIN_PRICE", "0.12"))
MAX_PRICE = float(os.getenv("MAX_PRICE", "0.88"))

# Edge mínimo
MIN_EDGE = float(os.getenv("MIN_EDGE", "0.02"))
MIN_EDGE_EXACT = float(os.getenv("MIN_EDGE_EXACT", "0.07"))

# ============================================================
# Bankroll
# ============================================================

START_BALANCE = float(os.getenv("START_BALANCE", "100.00"))
CITY_DISPLAY = {
    "new york": "New York",
    "london": "London",
    "paris": "Paris",
    "hong kong": "Hong Kong",
    "tokyo": "Tokyo",
    "seoul": "Seoul",
    "beijing": "Beijing",
    "sao paulo": "São Paulo",
    "milan": "Milan",
    "los angeles": "Los Angeles",
    "houston": "Houston",
    "austin": "Austin",
    "denver": "Denver",
    "seattle": "Seattle",
    "chicago": "Chicago",
    "phoenix": "Phoenix",
    "miami": "Miami",
    "atlanta": "Atlanta",
    "boston": "Boston",
    "toronto": "Toronto",
    "madrid": "Madrid",
    "mexico city": "Mexico City"
}
CITY_SLUG_NORMALIZE = {
    "new-york": "new york",
    "new york city": "new york",
    "nyc": "new york",
    "london": "london",
    "paris": "paris",
    "hong-kong": "hong kong",
    "tokyo": "tokyo",
    "seoul": "seoul",
    "beijing": "beijing",
    "sao-paulo": "sao paulo",
    "milan": "milan",
    "los-angeles": "los angeles",
    "houston": "houston",
    "austin": "austin",
    "denver": "denver",
    "seattle": "seattle",
    "chicago": "chicago",
    "phoenix": "phoenix",
    "miami": "miami",
    "atlanta": "atlanta",
    "boston": "boston",
    "toronto": "toronto",
    "madrid": "madrid",
    "mexico-city": "mexico city"
}

# ============================================================
# Carregamento de Cidades
# ============================================================

def load_cities():
    """Carrega a lista de cidades do arquivo cities.json"""
    cities_path = os.path.join(os.path.dirname(__file__), 'cities.json')
    try:
        with open(cities_path, 'r') as f:
            cities = json.load(f)
        return cities
    except FileNotFoundError:
        # Fallback: cidades padrão embutidas
        return [
            {"name": "New York", "lat": 40.7128, "lon": -74.0060},
            {"name": "London", "lat": 51.5074, "lon": -0.1278},
            {"name": "Paris", "lat": 48.8566, "lon": 2.3522},
            {"name": "Hong Kong", "lat": 22.3193, "lon": 114.1694},
            {"name": "Tokyo", "lat": 35.6762, "lon": 139.6503},
            {"name": "Seoul", "lat": 37.5665, "lon": 126.9780},
            {"name": "Beijing", "lat": 39.9042, "lon": 116.4074},
            {"name": "São Paulo", "lat": -23.5505, "lon": -46.6333},
            {"name": "Milan", "lat": 45.4642, "lon": 9.1900},
            {"name": "Los Angeles", "lat": 34.0522, "lon": -118.2437},
            {"name": "Houston", "lat": 29.7604, "lon": -95.3698},
            {"name": "Austin", "lat": 30.2672, "lon": -97.7431},
            {"name": "Denver", "lat": 39.7392, "lon": -104.9903},
            {"name": "Seattle", "lat": 47.6062, "lon": -122.3321},
            {"name": "Chicago", "lat": 41.8781, "lon": -87.6298},
            {"name": "Phoenix", "lat": 33.4484, "lon": -112.0740},
            {"name": "Miami", "lat": 25.7617, "lon": -80.1918},
            {"name": "Atlanta", "lat": 33.7490, "lon": -84.3880},
            {"name": "Boston", "lat": 42.3601, "lon": -71.0589},
            {"name": "Toronto", "lat": 43.6532, "lon": -79.3832},
            {"name": "Madrid", "lat": 40.4168, "lon": -3.7038},
            {"name": "Mexico City", "lat": 19.4326, "lon": -99.1332}
        ]
    except Exception as e:
        print(f"ERRO ao carregar cidades: {e}")
        return []

CITIES = load_cities()

# ============================================================
# Configurações de API
# ============================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "alexeller11/weather-quant-bot")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
WEATHERAPI_KEY = os.getenv("WEATHERAPI_KEY", "")

# ============================================================
# Configurações de Logging
# ============================================================

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")