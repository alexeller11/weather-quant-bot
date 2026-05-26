#!/usr/bin/env python3
"""
Configurações do Weather Quant Bot v3.
"""

import os
import json

# ============================================================
# Configurações de Risco
# ============================================================

TRADING_ENABLED = int(os.getenv("TRADING_ENABLED", "0"))
MIN_PROB_ABOVE_BELOW = float(os.getenv("MIN_PROB_ABOVE_BELOW", "0.70"))
MIN_TARGET_ZSCORE = float(os.getenv("MIN_TARGET_ZSCORE", "1.50"))
MAX_POSITION = float(os.getenv("MAX_POSITION", "2.00"))
MAX_TOTAL_EXPOSURE = float(os.getenv("MAX_TOTAL_EXPOSURE", "8.00"))
MAX_OPEN_TRADES = int(os.getenv("MAX_OPEN_TRADES", "4"))
KELLY_FRACTION = float(os.getenv("KELLY_FRACTION", "0.50"))

# Sigma caps
SIGMA_CAP_ABOVE_BELOW = float(os.getenv("SIGMA_CAP_ABOVE_BELOW", "3.6"))
SIGMA_CAP_EXACT = float(os.getenv("SIGMA_CAP_EXACT", "4.0"))

# Zona morta de probabilidade
PROB_DEADZONE_MIN = float(os.getenv("PROB_DEADZONE_MIN", "0.45"))
PROB_DEADZONE_MAX = float(os.getenv("PROB_DEADZONE_MAX", "0.55"))

# Liquidez
MIN_PRICE = float(os.getenv("MIN_PRICE", "0.12"))
MAX_PRICE = float(os.getenv("MAX_PRICE", "0.88"))

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
        print(f"AVISO: Arquivo {cities_path} não encontrado. Usando lista vazia.")
        return []
    except Exception as e:
        print(f"ERRO ao carregar cidades: {e}")
        return []

# Exporta a lista de cidades
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