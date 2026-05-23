# =========================================================
# WEATHER QUANT BOT — CONFIG
# =========================================================

import os

# =========================================================
# TELEGRAM
# =========================================================

TELEGRAM_TOKEN = os.getenv(
    "TELEGRAM_TOKEN",
    ""
)

CHAT_ID = os.getenv(
    "CHAT_ID",
    ""
)

# =========================================================
# BANKROLL
# =========================================================

START_BALANCE = 50.0

# =========================================================
# RISK
# =========================================================

KELLY_FRACTION = 0.50

MAX_POSITION = 10.0

MAX_TOTAL_EXPOSURE = 50.0

# =========================================================
# EDGE
# =========================================================

EDGE_THRESHOLD = 0.05

EDGE_THRESHOLD_EXACT = 0.10

# =========================================================
# EV
# =========================================================

MAX_EV = 1.8

# =========================================================
# MARKET FILTER
# =========================================================

MIN_MARKET_PRICE = 0.05

MAX_MARKET_PRICE = 0.95

MIN_LIQUIDITY_PRICE = 0.08

MAX_LIQUIDITY_PRICE = 0.92

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

    "new-york": "New York",

    "london": "London",

    "paris": "Paris",

    "hong-kong": "Hong Kong",

    "tokyo": "Tokyo",

    "seoul": "Seoul",

    "beijing": "Beijing",

    "sao-paulo": "São Paulo",

    "milan": "Milan",

    "los-angeles": "Los Angeles",

    "houston": "Houston",

    "austin": "Austin",

    "denver": "Denver",

    "seattle": "Seattle",

    "chicago": "Chicago",

    "phoenix": "Phoenix",

    "miami": "Miami",

    "atlanta": "Atlanta",

    "boston": "Boston",
}

# =========================================================
# NORMALIZE
# =========================================================

CITY_SLUG_NORMALIZE = {

    "New York": "new-york",

    "London": "london",

    "Paris": "paris",

    "Hong Kong": "hong-kong",

    "Tokyo": "tokyo",

    "Seoul": "seoul",

    "Beijing": "beijing",

    "São Paulo": "sao-paulo",

    "Sao Paulo": "sao-paulo",

    "Milan": "milan",

    "Los Angeles": "los-angeles",

    "Houston": "houston",

    "Austin": "austin",

    "Denver": "denver",

    "Seattle": "seattle",

    "Chicago": "chicago",

    "Phoenix": "phoenix",

    "Miami": "miami",

    "Atlanta": "atlanta",

    "Boston": "boston",
}

# =========================================================
# CITY COORDINATES BY SLUG
# =========================================================

CITY_COORDS_BY_SLUG = {

    "new-york": (40.7128, -74.0060),

    "london": (51.5072, -0.1276),

    "paris": (48.8566, 2.3522),

    "hong-kong": (22.3193, 114.1694),

    "tokyo": (35.6762, 139.6503),

    "seoul": (37.5665, 126.9780),

    "beijing": (39.9042, 116.4074),

    "sao-paulo": (-23.5505, -46.6333),

    "milan": (45.4642, 9.1900),

    "los-angeles": (34.0522, -118.2437),

    "houston": (29.7604, -95.3698),

    "austin": (30.2672, -97.7431),

    "denver": (39.7392, -104.9903),

    "seattle": (47.6062, -122.3321),

    "chicago": (41.8781, -87.6298),

    "phoenix": (33.4484, -112.0740),

    "miami": (25.7617, -80.1918),

    "atlanta": (33.7490, -84.3880),

    "boston": (42.3601, -71.0589),
}

# =========================================================
# CITY TIMEZONE MAPPING
# =========================================================

CITY_TIMEZONE = {

    "new-york": "America/New_York",

    "london": "Europe/London",

    "paris": "Europe/Paris",

    "hong-kong": "Asia/Hong_Kong",

    "tokyo": "Asia/Tokyo",

    "seoul": "Asia/Seoul",

    "beijing": "Asia/Shanghai",

    "sao-paulo": "America/Sao_Paulo",

    "milan": "Europe/Rome",

    "los-angeles": "America/Los_Angeles",

    "houston": "America/Chicago",

    "austin": "America/Chicago",

    "denver": "America/Denver",

    "seattle": "America/Los_Angeles",

    "chicago": "America/Chicago",

    "phoenix": "America/Phoenix",

    "miami": "America/New_York",

    "atlanta": "America/New_York",

    "boston": "America/New_York",
}

# =========================================================
# SIGMA INFLATION
# =========================================================

SIGMA_ENSEMBLE_INFLATION = {

    1: 1.4,

    2: 1.6,

    3: 1.9,

    4: 2.2,

    5: 2.5,
}

# =========================================================
# CLIMATOLOGICAL SIGMA
# =========================================================

CITY_SIGMA_CLIMO = {

    "new-york": 2.8,

    "london": 2.6,

    "paris": 2.4,

    "hong-kong": 3.2,

    "tokyo": 2.7,

    "seoul": 3.0,

    "beijing": 3.4,

    "sao-paulo": 2.0,

    "milan": 2.3,

    "los-angeles": 2.2,

    "houston": 3.1,

    "austin": 3.0,

    "denver": 3.4,

    "seattle": 2.9,

    "chicago": 3.8,

    "phoenix": 3.0,

    "miami": 3.4,

    "atlanta": 3.1,

    "boston": 3.3,
}

# =========================================================
# SIGMA MIN
# =========================================================

SIGMA_MIN_EXACT = 2.5

CITY_MIN_SIGMA = {

    "hong-kong": 3.0,

    "houston": 3.0,

    "austin": 3.0,

    "denver": 3.2,

    "chicago": 3.5,

    "miami": 3.2,

    "boston": 3.2,
}

# =========================================================
# CYCLE CONFIGURATION
# =========================================================

CYCLE_INTERVAL_SECONDS = int(
    os.getenv("CYCLE_INTERVAL_SECONDS", "300")
)
