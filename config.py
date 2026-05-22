# =========================================================
# WEATHER QUANT BOT — CONFIG
# =========================================================

import os

# =========================================================
# TELEGRAM
# =========================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")

# =========================================================
# GITHUB BACKUP
# =========================================================

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")

# =========================================================
# BANKROLL
# =========================================================

START_BALANCE = 50.0

# =========================================================
# RISCO / SIZING
# =========================================================

# Kelly fracionado
KELLY_FRACTION = 0.50

# Máximo por trade (% do bankroll)
MAX_POSITION = 0.08

# Máximo total de exposição em DÓLARES
# (você escolheu continuar usando cap fixo)
MAX_TOTAL_EXPOSURE = 40.0

# Máximo absoluto por trade em dólares
MAX_POSITION_DOLARES = 10.0

# EXACT usa stake menor
EXACT_STAKE_MULTIPLIER = 0.40

# =========================================================
# EDGE / EV
# =========================================================

EDGE_THRESHOLD = 0.06
EDGE_THRESHOLD_EXACT = 0.12

# EV muito alto normalmente é bug/anomalia
MAX_EV = 1.00

# =========================================================
# LIQUIDEZ
# =========================================================

MIN_MARKET_PRICE = 0.05
MAX_MARKET_PRICE = 0.95

MIN_LIQUIDITY_PRICE = 0.07
MAX_LIQUIDITY_PRICE = 0.95

# =========================================================
# SIGMA / MODELO
# =========================================================

SIGMA_MIN_EXACT = 2.5

# inflação por dia
SIGMA_ENSEMBLE_INFLATION = {
    1: 1.20,
    2: 1.60,
    3: 1.90,
    4: 2.20,
    5: 2.50,
}

# sigma climatológico por cidade
CITY_SIGMA_CLIMO = {
    "london": 1.8,
    "paris": 1.8,
    "milan": 1.9,
    "hong-kong": 1.5,
    "tokyo": 1.7,
    "seoul": 2.0,
    "los-angeles": 1.6,
    "houston": 2.0,
    "austin": 2.3,
    "denver": 2.0,
    "seattle": 2.0,
}

# sigma mínimo por cidade
CITY_MIN_SIGMA = {
    "denver": 2.5,
}

# =========================================================
# CIDADES
# =========================================================

CITY_SLUGS = [
    "london",
    "paris",
    "milan",
    "hong-kong",
    "tokyo",
    "seoul",
    "los-angeles",
    "houston",
    "austin",
    "denver",
    "seattle",
]

# =========================================================
# DISPLAY
# =========================================================

CITY_DISPLAY = {
    "london": "London",
    "paris": "Paris",
    "milan": "Milan",
    "hong-kong": "Hong Kong",
    "tokyo": "Tokyo",
    "seoul": "Seoul",
    "los-angeles": "Los Angeles",
    "houston": "Houston",
    "austin": "Austin",
    "denver": "Denver",
    "seattle": "Seattle",
}

CITY_SLUG_NORMALIZE = {
    "hong kong": "hong-kong",
    "hong-kong": "hong-kong",
    "los angeles": "los-angeles",
    "los-angeles": "los-angeles",
}
