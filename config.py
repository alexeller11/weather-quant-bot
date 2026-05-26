# =========================================================
# WEATHER QUANT BOT — CONFIG
# FIX: MAX_FORECAST_DAY=3 (era 5)
#      EDGE_THRESHOLD_BY_DAY: edge mínimo cresce com o horizonte
# FIX #26: MIN_PROB_ABOVE_BELOW=0.55, MIN_PROB_BELOW=0.55
#      Impede trades onde o modelo tem < 55% de convicção na direção.
#      Edge positivo com prob baixa = mercado está certo, não nós.
# =========================================================

import os

# =========================================================
# TELEGRAM
# =========================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID        = os.getenv("CHAT_ID", "")

# =========================================================
# BANKROLL
# =========================================================

START_BALANCE = 50.0

# =========================================================
# RISK
# =========================================================

KELLY_FRACTION = 0.50

# MAX_POSITION: cap em DÓLARES por trade (usado em bot.py)
MAX_POSITION = 2.0

# MAX_KELLY_FRACTION_CAP: cap como fração do bankroll (usado em risk.py)
MAX_KELLY_FRACTION_CAP = 0.05

MAX_TOTAL_EXPOSURE   = 16.0
MAX_OPEN_TRADES      = 8
MAX_TRADES_PER_CYCLE = 3
MAX_TRADES_PER_CITY  = 1

# =========================================================
# HORIZONTE
# =========================================================

MAX_FORECAST_DAY = 3

# =========================================================
# EDGE
# =========================================================

EDGE_THRESHOLD_BY_DAY = {
    1: 0.15,
    2: 0.12,
    3: 0.16,
}

EDGE_THRESHOLD       = 0.12
EDGE_THRESHOLD_EXACT = 0.15

# =========================================================
# EV
# =========================================================

MAX_EV = 0.65

# =========================================================
# MARKET FILTER
# =========================================================

MIN_MARKET_PRICE    = 0.08
MAX_MARKET_PRICE    = 0.92
MIN_LIQUIDITY_PRICE = 0.12
MAX_LIQUIDITY_PRICE = 0.88

# =========================================================
# TRADING SAFETY
# =========================================================

TRADING_ENABLED = os.getenv("TRADING_ENABLED", "0") == "1"

PROBABILITY_DEAD_ZONE_LOW  = 0.45
PROBABILITY_DEAD_ZONE_HIGH = 0.55

MIN_TARGET_ZSCORE = 0.45
MIN_EV = 0.02

# =========================================================
# FIX #26: PROBABILIDADE MÍNIMA POR TIPO
#
# Por que isso é necessário:
#   Edge = model_prob - market_price
#   Se market_price = 0.08 e model_prob = 0.20, edge = +0.12
#   Parece bom, mas estamos dizendo que a prob é 20% — ou seja,
#   80% de chance de perder. O mercado com 8% está errado, mas
#   nós com 20% também não temos convicção suficiente para apostar.
#
# MIN_PROB_ABOVE_BELOW = 0.55:
#   Para apostar ABOVE, o modelo precisa achar >55% de chance de ABOVE.
#   Para apostar BELOW, o modelo precisa achar >55% de chance de BELOW.
#   Abaixo disso, o modelo está incerto demais na direção.
#
# Efeito esperado: reduzir número de trades, aumentar qualidade.
# =========================================================

MIN_PROB_ABOVE_BELOW = 0.55   # prob mínima para trades ABOVE
MIN_PROB_BELOW       = 0.55   # prob mínima para trades BELOW
# EXACT não tem esse filtro (lógica diferente — baixa prob é esperada)

# =========================================================
# POLYMARKET FEE
# =========================================================

POLYMARKET_FEE = 0.02

# =========================================================
# CIDADES
# =========================================================

CITY_SLUGS = [
    "new-york",
    "london",
    "paris",
    "hong-kong",
    "tokyo",
    "seoul",
    "beijing",
    "sao-paulo",
    "milan",
    "los-angeles",
    "houston",
    "austin",
    "denver",
    "seattle",
    "chicago",
    "phoenix",
    "miami",
    "atlanta",
    "boston",
]

# =========================================================
# CITY DISPLAY
# =========================================================

CITY_DISPLAY = {
    "new-york":     "New York",
    "london":       "London",
    "paris":        "Paris",
    "hong-kong":    "Hong Kong",
    "tokyo":        "Tokyo",
    "seoul":        "Seoul",
    "beijing":      "Beijing",
    "sao-paulo":    "São Paulo",
    "milan":        "Milan",
    "los-angeles":  "Los Angeles",
    "houston":      "Houston",
    "austin":       "Austin",
    "denver":       "Denver",
    "seattle":      "Seattle",
    "chicago":      "Chicago",
    "phoenix":      "Phoenix",
    "miami":        "Miami",
    "atlanta":      "Atlanta",
    "boston":       "Boston",
    "toronto":      "Toronto",
    "madrid":       "Madrid",
    "mexico-city":  "Mexico City",
}

# =========================================================
# NORMALIZE
# =========================================================

CITY_SLUG_NORMALIZE = {
    "New York":     "new-york",
    "London":       "london",
    "Paris":        "paris",
    "Hong Kong":    "hong-kong",
    "Tokyo":        "tokyo",
    "Seoul":        "seoul",
    "Beijing":      "beijing",
    "São Paulo":    "sao-paulo",
    "Sao Paulo":    "sao-paulo",
    "Milan":        "milan",
    "Los Angeles":  "los-angeles",
    "Houston":      "houston",
    "Austin":       "austin",
    "Denver":       "denver",
    "Seattle":      "seattle",
    "Chicago":      "chicago",
    "Phoenix":      "phoenix",
    "Miami":        "miami",
    "Atlanta":      "atlanta",
    "Boston":       "boston",
    "Toronto":      "toronto",
    "Madrid":       "madrid",
    "Mexico City":  "mexico-city",
}

# =========================================================
# CITY COORDINATES BY SLUG
# =========================================================

CITY_COORDS_BY_SLUG = {
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
# CITY TIMEZONE MAPPING
# =========================================================

CITY_TIMEZONE = {
    "new-york":    "America/New_York",
    "london":      "Europe/London",
    "paris":       "Europe/Paris",
    "hong-kong":   "Asia/Hong_Kong",
    "tokyo":       "Asia/Tokyo",
    "seoul":       "Asia/Seoul",
    "beijing":     "Asia/Shanghai",
    "sao-paulo":   "America/Sao_Paulo",
    "milan":       "Europe/Rome",
    "los-angeles": "America/Los_Angeles",
    "houston":     "America/Chicago",
    "austin":      "America/Chicago",
    "denver":      "America/Denver",
    "seattle":     "America/Los_Angeles",
    "chicago":     "America/Chicago",
    "phoenix":     "America/Phoenix",
    "miami":       "America/New_York",
    "atlanta":     "America/New_York",
    "boston":      "America/New_York",
    "toronto":     "America/Toronto",
    "madrid":      "Europe/Madrid",
    "mexico-city": "America/Mexico_City",
}

# =========================================================
# SIGMA INFLATION
# =========================================================

SIGMA_ENSEMBLE_INFLATION = {
    1: 1.0,
    2: 1.0,
    3: 1.0,
    4: 1.0,
    5: 1.0,
}

# =========================================================
# CLIMATOLOGICAL SIGMA
# =========================================================

CITY_SIGMA_CLIMO = {
    "new-york":    2.3,
    "london":      2.2,
    "paris":       2.1,
    "hong-kong":   2.6,
    "tokyo":       2.2,
    "seoul":       2.4,
    "beijing":     2.6,
    "sao-paulo":   2.0,
    "milan":       2.1,
    "los-angeles": 2.0,
    "houston":     2.7,
    "austin":      2.6,
    "denver":      2.8,
    "seattle":     2.4,
    "chicago":     2.9,
    "phoenix":     2.6,
    "miami":       2.7,
    "atlanta":     2.5,
    "boston":      2.5,
    "toronto":     2.5,
    "madrid":      2.1,
    "mexico-city": 2.0,
}

# =========================================================
# SIGMA MIN/MAX
# =========================================================

SIGMA_MIN_EXACT = 1.6

SIGMA_MAX_ABOVE_BELOW = 3.6
SIGMA_MAX_EXACT = 2.8

CITY_MIN_SIGMA = {
    "hong-kong":   2.4,
    "houston":     2.5,
    "austin":      2.5,
    "denver":      2.6,
    "chicago":     2.7,
    "miami":       2.5,
    "boston":      2.4,
    "toronto":     2.4,
}

# =========================================================
# CYCLE CONFIGURATION
# =========================================================

CYCLE_INTERVAL_SECONDS = int(os.getenv("CYCLE_INTERVAL_SECONDS", "300"))
