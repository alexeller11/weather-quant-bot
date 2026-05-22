# =========================================================
# WEATHER QUANT BOT — CONFIG
# =========================================================

# =========================================================
# BANKROLL
# =========================================================

START_BALANCE = 50.0

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

    "Milan": "milan",

    "Los Angeles": "los-angeles",

    "Houston": "houston",

    "Austin": "austin",

    "Denver": "denver",

    "Seattle": "seattle",
}

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
]

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
# EXPOSIÇÃO
# =========================================================

MAX_TOTAL_EXPOSURE = 20.0

# =========================================================
# MARKET FILTER
# =========================================================

MIN_MARKET_PRICE = 0.05

MAX_MARKET_PRICE = 0.95

MIN_LIQUIDITY_PRICE = 0.08

MAX_LIQUIDITY_PRICE = 0.92

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
}
