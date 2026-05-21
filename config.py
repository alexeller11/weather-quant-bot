import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID        = os.getenv("CHAT_ID", "")

# ── Edge & risk ──────────────────────────────────────────────────────────────
EDGE_THRESHOLD     = 0.05
MAX_POSITION       = 0.10
# Exposição máxima total em aberto (USD fixo).
# Com $5 por trade e ~8 posições simultâneas = $40.
# Antes era fração do saldo (0.15 * $43 = $6.46), o que bloqueava tudo.
MAX_TOTAL_EXPOSURE = 40.0
KELLY_FRACTION     = 0.5

# ── Polymarket fee ───────────────────────────────────────────────────────────
POLYMARKET_FEE = 0.02

# ── Bankroll ─────────────────────────────────────────────────────────────────
START_BALANCE = 1000

# ── Mercado ──────────────────────────────────────────────────────────────────
MIN_MARKET_PRICE = 0.03
MAX_MARKET_PRICE = 0.97

# ── Filtro de liquidez ────────────────────────────────────────────────────────
# Mercados com preço abaixo de MIN_LIQUIDITY_PRICE têm spread bid/ask enorme:
# o EV calculado é ilusório porque não há contraparte a esse preço.
# Ex: Toronto 17°C a $0.055 gerou EV +943% — impossível executar na prática.
# Também filtra o teto: mercados >MAX_LIQUIDITY_PRICE estão quase resolvidos.
MIN_LIQUIDITY_PRICE = 0.08
MAX_LIQUIDITY_PRICE = 0.92

# ── EV cap ───────────────────────────────────────────────────────────────────
# EVs acima deste valor são sinais de modelo mal calibrado ou mercado ilíquido.
# +150% (EV=1.5) é o teto conservador. Wellington 15°C (EV=+197%) é exemplo
# de modelo com sigma subestimado para clima costeiro — mercado estava certo.
MAX_EV = 1.5

# ── Sigma mínimo por cidade ───────────────────────────────────────────────────
# Cidades costeiras e de altitude têm variabilidade real muito maior que o
# ensemble captura. O sigma_used nunca fica abaixo deste valor por cidade.
# Formato: { "slug": min_sigma_celsius }
CITY_MIN_SIGMA = {
    "wellington":    2.5,   # muito ventoso, clima costeiro extremamente variável
    "san-francisco": 2.0,   # marine layer, microclimas extremos
    "seattle":       1.8,   # influência oceânica, frentes frequentes
    "denver":        2.5,   # altitude + planícies, variações bruscas
    "chicago":       2.0,   # lago Michigan + corredor de tempestades
    "new-york":      1.8,   # costeiro, influência atlântica
    "toronto":       1.8,   # lago Ontario
    "london":        1.5,   # clima atlântico, frentes frequentes
    "amsterdam":     1.5,   # costeiro/planície
    "buenos-aires":  1.8,   # pampa, frentes súbitas
}

# ── Cidades — FONTE ÚNICA DE VERDADE ─────────────────────────────────────────
# Todos os módulos importam daqui. Nunca defina coords ou nomes em outro lugar.
# Lista atualizada com todas as cidades visíveis na Polymarket Weather (mai/2026).

CITY_SLUGS = [
    "seoul",
    "tokyo",
    "los-angeles",
    "london",
    "paris",
    "houston",
    "hong-kong",
    "milan",
    "denver",
    "austin",
    "seattle",
    "beijing",
    # Adicionadas — visíveis na Polymarket Weather em mai/2026
    "wellington",
    "new-york",
    "chicago",
    "miami",
    "san-francisco",
    "toronto",
    "sydney",
    "singapore",
    "dubai",
    "amsterdam",
    "berlin",
    "madrid",
    "bangkok",
    "mumbai",
    "johannesburg",
    "mexico-city",
    "buenos-aires",
    "sao-paulo",
    "lagos",
    "cairo",
]

CITY_COORDS_BY_SLUG = {
    "seoul":         (37.5665, 126.9780),
    "tokyo":         (35.6762, 139.6503),
    "los-angeles":   (34.0522, -118.2437),
    "london":        (51.5072,  -0.1276),
    "paris":         (48.8566,   2.3522),
    "houston":       (29.7604, -95.3698),
    "hong-kong":     (22.3193, 114.1694),
    "milan":         (45.4642,   9.1900),
    "denver":        (39.7392, -104.9903),
    "austin":        (30.2672,  -97.7431),
    "seattle":       (47.6062, -122.3321),
    "beijing":       (39.9042, 116.4074),
    # Novas
    "wellington":    (-41.2866, 174.7756),
    "new-york":      (40.7128,  -74.0060),
    "chicago":       (41.8781,  -87.6298),
    "miami":         (25.7617,  -80.1918),
    "san-francisco": (37.7749, -122.4194),
    "toronto":       (43.6532,  -79.3832),
    "sydney":        (-33.8688, 151.2093),
    "singapore":     ( 1.3521,  103.8198),
    "dubai":         (25.2048,   55.2708),
    "amsterdam":     (52.3676,    4.9041),
    "berlin":        (52.5200,   13.4050),
    "madrid":        (40.4168,   -3.7038),
    "bangkok":       (13.7563,  100.5018),
    "mumbai":        (19.0760,   72.8777),
    "johannesburg":  (-26.2041,  28.0473),
    "mexico-city":   (19.4326,  -99.1332),
    "buenos-aires":  (-34.6037,  -58.3816),
    "sao-paulo":     (-23.5505,  -46.6333),
    "lagos":         ( 6.5244,    3.3792),
    "cairo":         (30.0444,   31.2357),
}

CITY_DISPLAY = {
    "seoul":         "Seoul",
    "tokyo":         "Tokyo",
    "los-angeles":   "Los Angeles",
    "london":        "London",
    "paris":         "Paris",
    "houston":       "Houston",
    "hong-kong":     "Hong Kong",
    "milan":         "Milan",
    "denver":        "Denver",
    "austin":        "Austin",
    "seattle":       "Seattle",
    "beijing":       "Beijing",
    "wellington":    "Wellington",
    "new-york":      "New York",
    "chicago":       "Chicago",
    "miami":         "Miami",
    "san-francisco": "San Francisco",
    "toronto":       "Toronto",
    "sydney":        "Sydney",
    "singapore":     "Singapore",
    "dubai":         "Dubai",
    "amsterdam":     "Amsterdam",
    "berlin":        "Berlin",
    "madrid":        "Madrid",
    "bangkok":       "Bangkok",
    "mumbai":        "Mumbai",
    "johannesburg":  "Johannesburg",
    "mexico-city":   "Mexico City",
    "buenos-aires":  "Buenos Aires",
    "sao-paulo":     "São Paulo",
    "lagos":         "Lagos",
    "cairo":         "Cairo",
}

# qualquer variação de nome/capitalização → slug canônico
CITY_SLUG_NORMALIZE = {
    "seoul":          "seoul",
    "tokyo":          "tokyo",
    "los-angeles":    "los-angeles",
    "los angeles":    "los-angeles",
    "losangeles":     "los-angeles",
    "london":         "london",
    "paris":          "paris",
    "houston":        "houston",
    "hong-kong":      "hong-kong",
    "hong kong":      "hong-kong",
    "hongkong":       "hong-kong",
    "milan":          "milan",
    "denver":         "denver",
    "austin":         "austin",
    "seattle":        "seattle",
    "beijing":        "beijing",
    "wellington":     "wellington",
    "new-york":       "new-york",
    "new york":       "new-york",
    "newyork":        "new-york",
    "chicago":        "chicago",
    "miami":          "miami",
    "san-francisco":  "san-francisco",
    "san francisco":  "san-francisco",
    "sanfrancisco":   "san-francisco",
    "toronto":        "toronto",
    "sydney":         "sydney",
    "singapore":      "singapore",
    "dubai":          "dubai",
    "amsterdam":      "amsterdam",
    "berlin":         "berlin",
    "madrid":         "madrid",
    "bangkok":        "bangkok",
    "mumbai":         "mumbai",
    "johannesburg":   "johannesburg",
    "mexico-city":    "mexico-city",
    "mexico city":    "mexico-city",
    "mexicocity":     "mexico-city",
    "buenos-aires":   "buenos-aires",
    "buenos aires":   "buenos-aires",
    "buenosaires":    "buenos-aires",
    "sao-paulo":      "sao-paulo",
    "sao paulo":      "sao-paulo",
    "são paulo":      "sao-paulo",
    "lagos":          "lagos",
    "cairo":          "cairo",
}

# ── GitHub Sync ───────────────────────────────────────────────────────────────
# Preencha no .env ou nas Variables do Railway.
# GITHUB_TOKEN  = Personal Access Token com permissão "repo"
# GITHUB_REPO   = "seu_usuario/weather-quant-bot"
# GITHUB_BRANCH = "main"
# (lidos diretamente pelo github_sync.py via os.getenv)
