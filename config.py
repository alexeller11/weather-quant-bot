# =========================================================
# WEATHER QUANT BOT — CONFIG v3
# Corrigido: MAX_TOTAL_EXPOSURE e MAX_OPEN_TRADES alinhados
#            com CHANGELOG (eram 24/$12 no arquivo, deveriam
#            ser 8/$4 conforme emergency reset documentado).
# Corrigido: MIN_PROB_ABOVE_BELOW 0.55 → 0.70 (auditoria
#            mostra win rate ~0% abaixo de 0.70).
# Corrigido: MIN_TARGET_ZSCORE 0.45 → 1.50 (targets dentro
#            de 1 sigma do forecast são zona de ruído puro).
# Adicionado: Toronto, Madrid, Mexico City em CITY_SLUGS.
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

# ALINHADO COM CHANGELOG — emergency reset reduziu para $8 e 4 abertos
MAX_TOTAL_EXPOSURE   = 8.0
MAX_OPEN_TRADES      = 4
MAX_TRADES_PER_CYCLE = 2
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

# CORRIGIDO: era 0.45 — targets dentro de 1.5 sigma são ruído
MIN_TARGET_ZSCORE = 1.50
MIN_EV = 0.02

# =========================================================
# PROBABILIDADE MÍNIMA POR TIPO
#
# Dados dos 26 trades fechados:
#   model_prob < 0.70 → win rate ~18% (19/21 perdas)
#   model_prob >= 0.70 → win rate ~71% (5/7 wins)
#
# CORRIGIDO: era 0.55 — sobe para 0.70 baseado nos dados reais.
# Efeito: ~80% menos entradas, mas nas que entrar o modelo
# tem convicção real, não está apostando na zona de incerteza.
# =========================================================

MIN_PROB_ABOVE_BELOW = 0.70   # CORRIGIDO: era 0.55
MIN_PROB_BELOW       = 0.70   # CORRIGIDO: era 0.55

# =========================================================
# POLYMARKET FEE
# =========================================================

POLYMARKET_FEE = 0.02

# =========================================================
# CIDADES — expandido para aumentar frequência de oportunidades
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
    "toronto",
    "madrid",
    "mexico-city",
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
    "new-york":    2.8,
    "london":      2.8,
    "paris":       2.8,
    "hong-kong":   3.0,
    "tokyo":       2.8,
    "seoul":       3.0,
    "beijing":     3.0,
    "sao-paulo":   2.5,
    "milan":       2.8,
    "los-angeles": 2.5,
    "houston":     3.2,
    "austin":      3.2,
    "denver":      3.5,
    "seattle":     3.0,
    "chicago":     3.5,
    "phoenix":     3.0,
    "miami":       3.2,
    "atlanta":     3.0,
    "boston":      3.0,
    "toronto":     3.0,
    "madrid":      2.8,
    "mexico-city": 2.5,
}

# =========================================================
# SIGMA MIN/MAX
# =========================================================

SIGMA_MIN_EXACT = 1.6

# CORRIGIDO: era 3.6 — com sigma base agora em 2.8–3.5,
# o cap precisa ser mais alto para não bloquear trades legítimos.
# O filtro real agora é MIN_TARGET_ZSCORE=1.5 e MIN_PROB=0.70.
SIGMA_MAX_ABOVE_BELOW = 4.5
SIGMA_MAX_EXACT = 3.0

CITY_MIN_SIGMA = {
    "hong-kong":   2.8,
    "houston":     3.0,
    "austin":      3.0,
    "denver":      3.2,
    "chicago":     3.2,
    "miami":       3.0,
    "boston":      2.8,
    "toronto":     2.8,
}

# =========================================================
# CYCLE CONFIGURATION
# =========================================================

CYCLE_INTERVAL_SECONDS = int(os.getenv("CYCLE_INTERVAL_SECONDS", "300"))
