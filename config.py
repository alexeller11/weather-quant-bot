#!/usr/bin/env python3
"""config.py — Configurações do Weather Quant Bot

Fonte única de parâmetros. Nenhum outro módulo deve redefinir estes
valores localmente: quem precisa deles importa daqui, para que override
por variável de ambiente funcione de verdade.

Cidades vêm de cities.json. Uma cidade com "active": false continua em
CITY_COORDS/CITY_TZ (settlement precisa das coordenadas para liquidar
trades já abertos) mas fica FORA de CITIES — ou seja, não gera novas
entradas.

Quando uma cidade tem "station_lat"/"station_lon", essas coordenadas são
usadas para forecast e liquidação em vez do centro da cidade: os
mercados de temperatura resolvem por uma estação específica, não pelo
ponto de grade do centro urbano.
"""

import os
import json
import logging

logger = logging.getLogger(__name__)

# AUDITORIA bug #17: aceitar "1"/"true"/"yes"/"on" (case-insensitive).
# Antes int(...) crashava ao import com TRADING_ENABLED=true/yes.
def _parse_bool_env(name: str, default: str = "0") -> bool:
    raw = (os.getenv(name) or default).strip().lower()
    return raw in ("1", "true", "yes", "on", "t", "y")

TRADING_ENABLED = _parse_bool_env("TRADING_ENABLED", "0")

MIN_PROB_ABOVE_BELOW = float(os.getenv("MIN_PROB_ABOVE_BELOW", "0.65"))

MIN_TARGET_ZSCORE = float(os.getenv("MIN_TARGET_ZSCORE", "0.7"))
MAX_POSITION = float(os.getenv("MAX_POSITION", "4.00"))
MAX_TOTAL_EXPOSURE = float(os.getenv("MAX_TOTAL_EXPOSURE", "20.00"))
MAX_OPEN_TRADES = int(os.getenv("MAX_OPEN_TRADES", "5"))
KELLY_FRACTION = float(os.getenv("KELLY_FRACTION", "0.50"))
MAX_KELLY_FRACTION_CAP = float(os.getenv("MAX_KELLY_FRACTION_CAP", "0.50"))
MIN_EDGE = float(os.getenv("MIN_EDGE", "0.015"))
MIN_EDGE_EXACT = float(os.getenv("MIN_EDGE_EXACT", "0.04"))
MIN_EV = float(os.getenv("MIN_EV", "0.05"))
EDGE_THRESHOLD = MIN_EDGE
MAX_FORECAST_DAY = int(os.getenv("MAX_FORECAST_DAY", "3"))
SIGMA_CAP_ABOVE_BELOW = float(os.getenv("SIGMA_CAP_ABOVE_BELOW", "6.0"))
SIGMA_CAP_EXACT = float(os.getenv("SIGMA_CAP_EXACT", "6.0"))
SIGMA_MAX_ABOVE_BELOW = SIGMA_CAP_ABOVE_BELOW

# SIGMA_MIN: piso de 2.0 impedia o calibrador de convergir para o erro
# real observado (desvio-padrao de 1.72C em 102 pares forecast/real no
# historico de 2026-06/07). Piso agora em 1.0.
SIGMA_MIN = float(os.getenv("SIGMA_MIN", "1.0"))
SIGMA_MAX = float(os.getenv("SIGMA_MAX", "8.0"))

# Stake minimo por trade. Sem isto, o truncamento de shares
# (int(stake/price)) gerava posicoes de $0.20 que so poluem a estatistica.
MIN_TRADE_STAKE = float(os.getenv("MIN_TRADE_STAKE", "1.00"))
PROB_DEADZONE_MIN = float(os.getenv("PROB_DEADZONE_MIN", "0.45"))
PROB_DEADZONE_MAX = float(os.getenv("PROB_DEADZONE_MAX", "0.55"))
PROBABILITY_DEAD_ZONE_LOW = PROB_DEADZONE_MIN
PROBABILITY_DEAD_ZONE_HIGH = PROB_DEADZONE_MAX

# ── Circuit breaker de perda diária ─────────────────────────────
MAX_DAILY_LOSS = float(os.getenv("MAX_DAILY_LOSS", "10.00"))

# Precos abaixo de 0.08 indicam mercado iliquido ou ja "decidido".
MIN_PRICE = float(os.getenv("MIN_PRICE", "0.08"))

# Piso separado para RANGE2 — buckets raros têm preço baixo por natureza
MIN_PRICE_RANGE2 = float(os.getenv("MIN_PRICE_RANGE2", "0.04"))

MAX_PRICE = float(os.getenv("MAX_PRICE", "0.88"))
START_BALANCE = float(os.getenv("START_BALANCE", "100.00"))

# Filtros de mercado — aplicados em gamma_parser.market_is_healthy().
# Existiam desde o inicio mas nenhum modulo os lia: o unico filtro real
# era preco entre 0.03 e 0.97 com tolerancia de spread de 15pp.
MIN_MARKET_LIQUIDITY = float(os.getenv("MIN_MARKET_LIQUIDITY", "100.00"))
MIN_MARKET_VOLUME = float(os.getenv("MIN_MARKET_VOLUME", "250.00"))
MAX_IMPLIED_SPREAD = float(os.getenv("MAX_IMPLIED_SPREAD", "0.08"))

# ── Paper execution (simulação contra order book real) ──────────
ORDERBOOK_TIMEOUT = int(os.getenv("ORDERBOOK_TIMEOUT", "5"))
PAPER_EXECUTION_REQUIRED = _parse_bool_env("PAPER_EXECUTION_REQUIRED", "0")
PAPER_MAX_SLIPPAGE = float(os.getenv("PAPER_MAX_SLIPPAGE", "0.05"))
PAPER_MIN_FILL_RATIO = float(os.getenv("PAPER_MIN_FILL_RATIO", "0.80"))

# ── Parâmetros antes hardcoded em risk.py ────────────────────────
MIN_PROB_RANGE2 = float(os.getenv("MIN_PROB_RANGE2", "0.04"))
MIN_EDGE_RANGE2 = float(os.getenv("MIN_EDGE_RANGE2", "0.02"))
MIN_EDGE_NO = float(os.getenv("MIN_EDGE_NO", "0.15"))
MAX_PROB_FOR_NO = float(os.getenv("MAX_PROB_FOR_NO", "0.35"))
FEE_RATE = float(os.getenv("FEE_RATE", "0.02"))
MAX_PRICE_RANGE2 = float(os.getenv("MAX_PRICE_RANGE2", "0.70"))
# Edge maximo aceito em RANGE2. Edge muito grande num bucket estreito é
# sinal de erro de modelo/dado, nao de oportunidade.
MAX_EDGE_RANGE2 = float(os.getenv("MAX_EDGE_RANGE2", "0.25"))

# Distancia maxima (em sigmas) entre a previsao e a borda do bucket para
# aceitar COMPRA (YES) de EXACT/RANGE2. Gate de sanidade fisica: sem ele
# o bot comprou 22 buckets de 74-85F em Los Angeles com previsao de
# 90-100F — 0 acertos em 22.
MAX_BUCKET_ZDIST = float(os.getenv("MAX_BUCKET_ZDIST", "1.0"))
MIN_PRICE_YES_FOR_NO = float(os.getenv("MIN_PRICE_YES_FOR_NO", "0.45"))
# RANGE2/EXACT sao buckets estreitos; NO neles muitas vezes custa caro
# mesmo quando YES fica abaixo de 0.45. Mantem ABOVE/BELOW conservador,
# mas deixa o lado NO de bucket passar para os demais guardrails.
MIN_PRICE_YES_FOR_NO_RANGE2 = float(os.getenv("MIN_PRICE_YES_FOR_NO_RANGE2", "0.20"))
MAX_EVENT_EXPOSURE = float(os.getenv("MAX_EVENT_EXPOSURE", str(MAX_POSITION)))

# ── Calibração de sigma ──────────────────────────────────────────
# Numero minimo de residuos por (cidade, condicao) antes de o sigma
# empirico comecar a puxar o sigma base, e constante de shrinkage:
# peso = n / (n + SIGMA_SHRINK_K).
SIGMA_MIN_SAMPLES = int(os.getenv("SIGMA_MIN_SAMPLES", "5"))
SIGMA_SHRINK_K = float(os.getenv("SIGMA_SHRINK_K", "10.0"))

# ── Ajuste ML da probabilidade ───────────────────────────────────
# ML_BLEND_WEIGHT=0 DESLIGA o blend. Ficou em 0.30 sem trava relativa a
# probabilidade fisica e produziu model_prob=0.30 para buckets com
# probabilidade real de 0.002 (previsao de 97F contra bucket de 78-79F),
# fabricando edge onde nao havia: 29 trades incoerentes, -$44.19
# realizados, 0 acertos em 23 entradas nas faixas 0.1-0.4.
# So voltar a subir depois de validacao out-of-sample.
ML_BLEND_WEIGHT = float(os.getenv("ML_BLEND_WEIGHT", "0.0"))
# Desvio absoluto maximo que o ML pode aplicar sobre a prob fisica.
ML_MAX_DEVIATION = float(os.getenv("ML_MAX_DEVIATION", "0.05"))
# Fator maximo (multiplicativo) entre prob ajustada e prob fisica.
ML_MAX_RATIO = float(os.getenv("ML_MAX_RATIO", "3.0"))
ML_MIN_TRADES = int(os.getenv("ML_MIN_TRADES", "5"))

# ── Consenso multi-fonte ─────────────────────────────────────────
# REQUIRE_CONSENSUS=1 bloqueia a entrada quando a 2a fonte esta ausente
# ou indisponivel. Com 0 (default) o consenso passa por omissao — que é
# o que acontecia em todo o historico, por falta de WEATHERAPI_KEY.
REQUIRE_CONSENSUS = _parse_bool_env("REQUIRE_CONSENSUS", "0")
# Thresholds de divergencia entre fontes, em °C. RANGE2 estava em 3.5°C
# — mais de 3x a largura de um bucket de 2°F (1.11°C), o que nao filtra
# nada relevante para esse tipo de mercado.
CONSENSUS_MAX_DIFF_RANGE2 = float(os.getenv("CONSENSUS_MAX_DIFF_RANGE2", "1.5"))
CONSENSUS_MAX_DIFF_EXACT = float(os.getenv("CONSENSUS_MAX_DIFF_EXACT", "1.5"))
CONSENSUS_MAX_DIFF_DEFAULT = float(os.getenv("CONSENSUS_MAX_DIFF_DEFAULT", "2.5"))
# Sanidade da fonte secundaria antes do bias tracker. Divergencia bruta
# acima disso costuma ser dado quebrado/API errada, nao forecast discordante
# (ex.: London em agosto OM~25C e WeatherAPI~-0.5C).
CONSENSUS_MAX_RAW_DIFF = float(os.getenv("CONSENSUS_MAX_RAW_DIFF", "12.0"))

# Viés sistemático WeatherAPI-menos-OpenMeteo, por cidade. Descoberto em
# produção em 2026-08-03: WA reporta consistentemente ~2-3°C mais quente
# que OM (ex.: OM=27.9 WA=32.0, OM=35.2 WA=37.5, OM=38.1 WA=41.2 — sempre
# WA > OM). Comparar a diferença BRUTA contra CONSENSUS_MAX_DIFF_RANGE2
# (1.5°C) bloqueava 46% de todas as tentativas de trade por um viés de
# fonte, não por divergência real de previsão. Agora o viés é estimado
# por (média móvel de WA-OM por cidade, com shrinkage) e removido antes
# de comparar ao threshold — mesmo padrão de sigma_calibrator.py.
CONSENSUS_BIAS_WINDOW = int(os.getenv("CONSENSUS_BIAS_WINDOW", "40"))
CONSENSUS_BIAS_MIN_SAMPLES = int(os.getenv("CONSENSUS_BIAS_MIN_SAMPLES", "5"))
# K=3 (não 10, como em sigma_calibrator): o viés observado entre fontes é
# grande (~2-3°C) e consistente em direção — testado contra as leituras
# reais de 2026-08-03, K=3 converge para ~2.1°C em 6 amostras e passa a
# liberar os trades legítimos; K=10 ainda deixava residuo >1.5°C após 9
# amostras, continuando a bloquear por um viés que já era conhecido.
CONSENSUS_BIAS_SHRINK_K = float(os.getenv("CONSENSUS_BIAS_SHRINK_K", "3.0"))

# ── Analytics / Health ───────────────────────────────────────────
# health.json fica no filesystem efemero do Render. Um snapshot velho
# (o do repositorio estava congelado ha 15 dias) continuava a governar o
# kelly_factor apos cada restart. Acima desta idade, o health é ignorado.
HEALTH_MAX_AGE_HOURS = float(os.getenv("HEALTH_MAX_AGE_HOURS", "48"))

# ── Parâmetros antes hardcoded em forecast.py ───────────────────
BIAS_WINDOW_DAYS = int(os.getenv("BIAS_WINDOW_DAYS", "21"))
BIAS_MIN_SAMPLES = int(os.getenv("BIAS_MIN_SAMPLES", "3"))
FORECAST_CACHE_TTL = int(os.getenv("FORECAST_CACHE_TTL", "3600"))

# Retry com backoff para 429/502/503/504 da Open-Meteo. Descoberto em
# 2026-08-05: 98.4% das tentativas de trade bloqueadas por
# forecast_unavailable — get_forecast() desistia na primeira falha, sem
# nenhuma nova tentativa. O limite documentado da Open-Meteo (600
# req/min, 10k/dia) é bem folgado para o volume do bot (confirmado por
# teste direto: 11 chamadas em sequência do IP local, todas 200) — o mais
# provável é rate limit por IP de saida COMPARTILHADO do plano Free do
# Render entre varios clientes, nao volume proprio. Mesmo padrao de
# retry/backoff ja usado em settlement.get_actual_temperature().
FORECAST_RETRIES = int(os.getenv("FORECAST_RETRIES", "3"))
FORECAST_RETRY_STATUS = {429, 500, 502, 503, 504}

# Experimento 2026-08-05: testado BASE=10/CAP=20 (10s, 20s) contra o
# rate limit persistente da Open-Meteo. Resultado nos logs de producao:
# TODAS as 19 cidades do ciclo esgotaram as 3 tentativas com 429 mesmo
# assim (igual ao default 2s/4s) — o bloqueio dura mais que 30s
# consecutivos, entao nenhum backoff razoavel resolve por retry sozinho.
# Revertido para 2s/4s: o valor maior so deixava o ciclo bem mais lento
# (14min para ~15 cidades, vs ~2min30s antes) sem nenhum ganho real.
# Causa raiz exige solucao paga (Open-Meteo comercial ou IP dedicado) —
# ver decisao registrada em 2026-08-05 de nao gastar por enquanto.
FORECAST_RETRY_BACKOFF_BASE = int(os.getenv("FORECAST_RETRY_BACKOFF_BASE", "2"))
FORECAST_RETRY_BACKOFF_CAP = int(os.getenv("FORECAST_RETRY_BACKOFF_CAP", "8"))

# ── Parâmetros antes hardcoded em settlement.py ─────────────────
MAX_OPEN_TRADE_DAYS = int(os.getenv("MAX_OPEN_TRADE_DAYS", "7"))
SETTLE_TEMP_RETRIES = int(os.getenv("SETTLE_TEMP_RETRIES", "3"))

# ──────────────────────────────────────────────────────────────
# CIDADES — fonte única: cities.json
# build_city_maps() DERIVA todos os dicts/listas a partir do JSON.
# ──────────────────────────────────────────────────────────────

def _load_cities_json():
    """Carrega cities.json; retorna [] se não existir."""
    cities_path = os.path.join(os.path.dirname(__file__), "cities.json")
    try:
        with open(cities_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning("cities.json nao encontrado — usando fallback")
        return []
    except Exception as e:
        logger.error("ERRO ao carregar cities.json: %s", e)
        return []


def city_is_active(city: dict) -> bool:
    """Uma cidade sem "active" é considerada ativa (compat retroativa)."""
    return bool(city.get("active", True))


def resolution_coords(city: dict):
    """
    Coordenadas que devem ser usadas para forecast E liquidação.

    Prefere station_lat/station_lon quando presentes: os mercados de
    temperatura da Polymarket resolvem por uma estação de referência, e
    usar o centro da cidade produz divergência sistemática (em Los
    Angeles o centro ficou +12.3°F acima da temperatura implícita nos
    preços, com 26/26 vitórias em RANGE2/NO e 0/22 em RANGE2/YES — não
    por previsão, mas porque o bucket estava fora da faixa).
    """
    lat = city.get("station_lat")
    lon = city.get("station_lon")
    if lat is not None and lon is not None:
        return float(lat), float(lon)
    return float(city["lat"]), float(city["lon"])


def build_city_maps(cities_list):
    """
    A partir da lista de dicts de cities.json, constrói:
    CITY_DISPLAY — slug (com espaço) -> nome de exibição
    CITY_SLUG_NORMALIZE — todas as variantes (slug, aliases, display) -> slug canônico
    CITY_SLUGS — lista de slugs ATIVOS (com hífen)
    CITY_COORDS — slug (com hífen) -> (lat, lon) de resolução; inclui inativas
    CITY_TZ — slug (com hífen) -> timezone IANA; inclui inativas
    CITY_SLUG_ALIASES — slug (com hífen) -> lista de aliases

    Cidades inativas continuam em COORDS/TZ/NORMALIZE (settlement precisa
    liquidar trades já abertos) mas ficam fora de CITY_SLUGS e de CITIES.
    """
    city_display = {}
    city_slug_normalize = {}
    city_slugs = []
    city_coords = {}
    city_tz = {}
    city_slug_aliases = {}

    for c in cities_list:
        # Garantir chave "name" para compatibilidade com o bot.py
        if "name" not in c:
            c["name"] = c.get("display", c.get("slug", ""))

        slug = c["slug"]
        display = c["display"]
        tz = c["tz"]
        aliases = c.get("aliases", [])

        space_key = slug.replace("-", " ")
        city_display[space_key] = display

        city_slug_normalize[slug] = slug
        city_slug_normalize[space_key] = slug
        city_slug_normalize[display.lower()] = slug
        for alias in aliases:
            city_slug_normalize[alias] = slug
            city_slug_normalize[alias.replace("-", " ")] = slug

        if city_is_active(c):
            city_slugs.append(slug)
        city_coords[slug] = resolution_coords(c)
        city_tz[slug] = tz
        city_slug_aliases[slug] = aliases

    return city_display, city_slug_normalize, city_slugs, city_coords, city_tz, city_slug_aliases


_CITIES_RAW = _load_cities_json()

if _CITIES_RAW:
    (CITY_DISPLAY,
     CITY_SLUG_NORMALIZE,
     CITY_SLUGS,
     CITY_COORDS,
     CITY_TZ,
     CITY_SLUG_ALIASES) = build_city_maps(_CITIES_RAW)

    # CITIES = apenas as cidades que geram novas entradas.
    # ALL_CITIES = todas, incluindo inativas (settlement, dashboard).
    ALL_CITIES = _CITIES_RAW
    CITIES = [c for c in _CITIES_RAW if city_is_active(c)]

    _inactive = [c["slug"] for c in _CITIES_RAW if not city_is_active(c)]
    if _inactive:
        logger.warning("Cidades INATIVAS (sem novas entradas): %s", ", ".join(_inactive))

else:
    # Fallback hardcoded — mantido para robustez caso cities.json seja removido
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
        "mexico city": "Mexico City",
    }

    CITY_SLUG_NORMALIZE = {
        "new-york": "new york",
        "new york city": "new york",
        "nyc": "new york",
        "london": "london",
        "paris": "paris",
        "hong-kong": "hong kong",
        "hong kong": "hong kong",
        "tokyo": "tokyo",
        "seoul": "seoul",
        "beijing": "beijing",
        "sao-paulo": "sao paulo",
        "são paulo": "sao paulo",
        "milan": "milan",
        "los-angeles": "los angeles",
        "los angeles": "los angeles",
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
        "mexico-city": "mexico city",
        "mexico city": "mexico city",
    }

    CITY_SLUGS = [
        "new-york", "london", "paris", "hong-kong", "tokyo", "seoul",
        "beijing", "sao-paulo", "milan", "los-angeles", "houston", "austin",
        "denver", "seattle", "chicago", "phoenix", "miami", "atlanta",
        "boston", "toronto", "madrid", "mexico-city",
    ]

    _CITIES_FALLBACK = [
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
        {"name": "Mexico City", "lat": 19.4326, "lon": -99.1332},
    ]

    def load_cities():
        return _CITIES_FALLBACK

    CITIES = load_cities()
    ALL_CITIES = CITIES

    # ── Popula CITY_COORDS, CITY_TZ, CITY_SLUG_ALIASES a partir do fallback ──
    # Quando cities.json não existe, estes dicts eram deixados vazios,
    # causando "cidade desconhecida" em forecast.py e station_data.py.
    _CITY_TZ_MAP = {
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
        "toronto": "America/Toronto",
        "madrid": "Europe/Madrid",
        "mexico-city": "America/Mexico_City",
    }

    CITY_COORDS = {}
    CITY_TZ = {}
    CITY_SLUG_ALIASES = {}
    for slug in CITY_SLUGS:
        display = CITY_DISPLAY.get(slug.replace("-", " "), slug)
        name_key = display.lower() if isinstance(display, str) else slug
        for c in _CITIES_FALLBACK:
            if c["name"].lower() == name_key:
                CITY_COORDS[slug] = (c["lat"], c["lon"])
                break
        CITY_TZ[slug] = _CITY_TZ_MAP.get(slug, "UTC")
        CITY_SLUG_ALIASES[slug] = [slug.replace("-", " "), slug]

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
WEATHERAPI_KEY = os.getenv("WEATHERAPI_KEY", "")

# Fallback de forecast quando a Open-Meteo esgota as tentativas (rate
# limit persistente de IP compartilhado, ver forecast.py). Diferente da
# Open-Meteo, o limite do OpenWeatherMap e' por CHAVE, nao por IP — o
# problema de IP compartilhado do Render simplesmente nao se aplica.
# Free tier: 60 chamadas/min, 1M/mes, sem cartao de credito.
OPENWEATHERMAP_KEY = os.getenv("OPENWEATHERMAP_KEY", "")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
