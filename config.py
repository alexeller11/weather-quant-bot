# =========================================================
# WEATHER QUANT BOT — CONFIG
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
# 0.20 = nunca apostar mais de 20% do bankroll em um único trade via Kelly
MAX_KELLY_FRACTION_CAP = 0.05

MAX_TOTAL_EXPOSURE = 8.0
MAX_OPEN_TRADES = 4
MAX_TRADES_PER_CYCLE = 2
MAX_TRADES_PER_CITY = 1

# =========================================================
# EDGE
# =========================================================

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

# Emergency default: keep the bot in observation mode after a model reset.
# Set TRADING_ENABLED=1 only after checking the validation report.
TRADING_ENABLED = os.getenv("TRADING_ENABLED", "0") == "1"

PROBABILITY_DEAD_ZONE_LOW  = 0.45
PROBABILITY_DEAD_ZONE_HIGH = 0.55

# Reject trades where forecast is too close to the target relative to sigma.
MIN_TARGET_ZSCORE = 0.45

# Extreme quoted EV is usually stale/illiquid pricing or a bad probability.
MIN_EV = 0.02

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
    # FIX: cidades presentes no bankroll mas ausentes da config
    "toronto":      "Toronto",
    "madrid":       "Madrid",
    "mexico-city":  "Mexico City",
}

# =========================================================
# NORMALIZE — chaves são display names, valores são slugs
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
    # FIX: adicionadas
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
    # FIX: adicionadas
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
    # FIX: adicionadas
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
# SIGMA MIN
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
