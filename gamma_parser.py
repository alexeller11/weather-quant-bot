"""
gamma_parser.py — Parser de mercados da Polymarket Gamma API

CORREÇÕES DA AUDITORIA (v5.7):

1. TEMPERATURAS NEGATIVAS
   "Will the highest temperature in Toronto be -2°C or below?" era
   parseado como target = +2 (o sinal era descartado pela regex).
   Probabilidade E settlement saíam errados em qualquer mercado de
   inverno (Toronto, Denver, Beijing, Chicago, Boston...).
   Todas as regex agora aceitam '-?' antes do número.

2. REGEX DE BUCKET (range2) MAIS ESTRITA
   O padrão antigo '(\\d+)-(\\d+)°?[CcFf]?' tinha unidade totalmente
   opcional e casava qualquer "N-M" no texto (ex.: intervalos de datas
   "June 7-8"), criando mercados fantasmas. Agora a unidade (°F/°C ou
   F/C) é obrigatória logo após o limite superior, e os dois limites
   aceitam sinal negativo.

3. DATA DO MERCADO NO FUSO DA CIDADE
   Os slugs eram montados com a data UTC. Quando UTC já virou o dia
   mas a cidade não (ou vice-versa: Tóquio/Seul à frente do UTC), o
   bot buscava o evento do dia errado e gravava market_date deslocado,
   desalinhando forecast e settlement. Agora D+0/D+1 usam o dia LOCAL
   da cidade (forecast.city_today).
"""

import json
import logging
import re
import time
from datetime import datetime, timedelta

import requests

from bankroll import canonical_market_base, normalize_city_slug
from config import CITY_SLUG_ALIASES
from forecast import city_today

logger = logging.getLogger(__name__)


BASE_URL = "https://gamma-api.polymarket.com"
HEADERS  = {"User-Agent": "Mozilla/5.0"}


def _get_city_slugs(city):
    slug = normalize_city_slug(city)
    aliases = CITY_SLUG_ALIASES.get(slug, [slug])
    out = []
    for candidate in [slug, *aliases]:
        candidate = normalize_city_slug(candidate)
        if candidate and candidate not in out:
            out.append(candidate)
    return out or [slug]


def safe_request(url, retries=2, timeout=8):
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                logger.warning(f"Rate limit (429) para {url}")
                continue
            logger.warning(f"HTTP {r.status_code} para {url}")
        except Exception as e:
            logger.warning(f"Request error (tentativa {attempt+1}): {e}")
        if attempt < retries - 1:
            time.sleep(min(2 ** attempt, 4))
    return None


def detect_unit(question):
    """Detecta unidade da temperatura na pergunta."""
    q = question.lower()
    if "fahrenheit" in q or "°f" in q:
        return "F"
    if "celsius" in q or "°c" in q:
        return "C"
    
    # Busca por padrões como "72F" ou "22C"
    if re.search(r'\d+\s*f(?!\w)', q):
        return "F"
    if re.search(r'\d+\s*c(?!\w)', q):
        return "C"

    # Heurística: se números > 45 sem unidade explícita, provavelmente °F
    # (Abaixado de 55 para 45 para capturar dias amenos nos EUA)
    nums = re.findall(r'-?\d+', question)
    if nums:
        max_val = max(int(n) for n in nums)
        if max_val > 45:
            return "F"
    return "C"


# Número com sinal opcional: -2, 31, 74.5 ...
_NUM = r'(-?\d+(?:\.\d+)?)'

_RE_ABOVE  = re.compile(_NUM + r'\s*°?\s*[CcFf]?\s+or\s+(?:higher|above)', re.IGNORECASE)
_RE_BELOW  = re.compile(_NUM + r'\s*°?\s*[CcFf]?\s+or\s+(?:below|lower)', re.IGNORECASE)
# Bucket "48-49°F" / "-4 - -3°C": unidade OBRIGATÓRIA após o limite superior
_RE_RANGE2 = re.compile(_NUM + r'\s*[-–]\s*' + _NUM + r'\s*°\s*[CcFf]')
_RE_EXACT  = re.compile(_NUM + r'\s*°\s*[CcFf]')


def parse_question(question):
    """
    Reconhece os formatos da Polymarket:
      - "50°F or higher"     → above,  target=50,   unit=F
      - "-2°C or below"      → below,  target=-2,   unit=C
      - "48-49°F"            → range2, lo=48 hi=49, unit=F
      - "-4--3°C"            → range2, lo=-4 hi=-3, unit=C
      - "24°C"               → exact,  target=24,   unit=C
    """
    q = question.strip()
    unit = detect_unit(q)

    m = _RE_ABOVE.search(q)
    if m:
        target = float(m.group(1))
        return {"condition": "above", "target": target, "unit": unit}

    m = _RE_BELOW.search(q)
    if m:
        target = float(m.group(1))
        return {"condition": "below", "target": target, "unit": unit}

    m = _RE_RANGE2.search(q)
    if m:
        lo = float(m.group(1))
        hi = float(m.group(2))
        if hi < lo:
            lo, hi = hi, lo
        mid = round((lo + hi) / 2, 1)
        return {
            "condition": "range2",
            "target":    mid,
            "target_lo": lo,
            "target_hi": hi,
            "unit":      unit,
        }

    m = _RE_EXACT.search(q)
    if m:
        target = float(m.group(1))
        return {"condition": "exact", "target": target, "unit": unit}

    logger.info(f"  Ignorado (formato não reconhecido): {question}")
    return None


def market_is_healthy(yes_price, no_price):
    """
    Piso de 0.03 para aceitar buckets de 2°F que legitimamente têm
    preços baixos. O filtro real de entrada é MIN_PRICE em risk.py.
    """
    try:
        yes_price = float(yes_price)
        no_price  = float(no_price)
    except Exception:
        return False

    if yes_price <= 0 or yes_price >= 1:
        return False

    # Rejeita apenas mercados completamente resolvidos
    if yes_price < 0.03 or yes_price > 0.97:
        return False

    # Tolerância de spread de 15pp
    if abs((yes_price + no_price) - 1.0) > 0.15:
        return False

    return True


def _slug_variants(city, d):
    """Gera variantes de slug para a cidade e data (com e sem ano)."""
    month = d.strftime('%B').lower()
    day   = d.day
    year  = d.year
    variants = []
    for alias in _get_city_slugs(city):
        variants.append(f"highest-temperature-in-{alias}-on-{month}-{day}")
        variants.append(f"highest-temperature-in-{alias}-on-{month}-{day}-{year}")
    out = []
    for item in variants:
        if item not in out:
            out.append(item)
    return out


def _search_fallback(city, d):
    """Busca textual como fallback quando slug não funciona."""
    month = d.strftime('%B').lower()
    day   = d.day
    city_clean = normalize_city_slug(city).replace("-", " ")
    query = f"highest temperature {city_clean} {month} {day}"
    url   = f"{BASE_URL}/events?limit=10&active=true&q={requests.utils.quote(query)}"
    data  = safe_request(url)
    if not data or not isinstance(data, list):
        return None
    city_word = city_clean.split()[0]
    for event in data:
        title = (event.get("title") or event.get("name") or "").lower()
        if city_word in title and month[:3] in title:
            return event
    return None


def _event_key(event):
    return str(event.get("id") or event.get("slug") or event.get("title") or event.get("name") or "")


def fetch_markets(city):
    """
    Busca D+0 e D+1 — no calendário LOCAL da cidade.

    Retorna lista de mercados válidos com condition, target, unit,
    yes_price. Para buckets range2, inclui target_lo e target_hi.
    """
    city_slug = normalize_city_slug(city)
    all_markets = []
    seen_market_keys = set()

    local_today = datetime.strptime(city_today(city_slug), "%Y-%m-%d").date()

    for i in range(0, 2):  # D+0 e D+1 locais
        d = local_today + timedelta(days=i)

        events = []
        seen_events = set()
        for slug in _slug_variants(city_slug, d):
            logger.debug(f"  Slug: {slug}")
            data = safe_request(f"{BASE_URL}/events?slug={slug}")
            if data and isinstance(data, list) and len(data) > 0:
                for event in data:
                    ekey = _event_key(event)
                    if ekey and ekey not in seen_events:
                        seen_events.add(ekey)
                        events.append(event)
            time.sleep(0.2)

        if not events:
            event = _search_fallback(city_slug, d)
            if event:
                logger.info(f"  Encontrado via busca: {event.get('slug','')}")
                events.append(event)

        if not events:
            logger.info(f"  Sem evento para {city_slug} {d.strftime('%B %d')}")
            continue

        for event in events:
            event_slug = event.get("slug", "")
            event_id = event.get("id", "")
            for market in event.get("markets", []):
                try:
                    question  = market.get("question", "")
                    gamma_market_id = market.get("id")
                    if not gamma_market_id:
                        continue

                    outcome_prices = market.get("outcomePrices")
                    if not outcome_prices:
                        continue

                    prices = json.loads(outcome_prices) if isinstance(outcome_prices, str) else list(outcome_prices)
                    if len(prices) < 2:
                        continue

                    yes_price = float(prices[0])
                    no_price  = float(prices[1])

                    if not market_is_healthy(yes_price, no_price):
                        logger.info(f"  Market unhealthy (yes={yes_price:.3f} no={no_price:.3f})")
                        continue

                    parsed = parse_question(question)
                    if not parsed:
                        continue

                    market_key = canonical_market_base(
                        city=city_slug,
                        market_date=d.strftime("%Y-%m-%d"),
                        condition=parsed["condition"],
                        target=parsed["target"],
                        unit=parsed["unit"],
                        target_lo=parsed.get("target_lo"),
                        target_hi=parsed.get("target_hi"),
                    )
                    if market_key in seen_market_keys:
                        continue
                    seen_market_keys.add(market_key)

                    entry = {
                        "market_id":      market_key,
                        "market_key":     market_key,
                        "gamma_market_id": str(gamma_market_id),
                        "gamma_event_id":  str(event_id),
                        "question":       question,
                        "market_date":    d.strftime("%Y-%m-%d"),
                        "event_slug":     event_slug,
                        "city_slug":      city_slug,
                        "condition":      parsed["condition"],
                        "target":         parsed["target"],
                        "unit":           parsed["unit"],
                        "yes_price":      yes_price,
                        "no_price":       no_price,
                    }
                    if parsed["condition"] == "range2":
                        entry["target_lo"] = parsed["target_lo"]
                        entry["target_hi"] = parsed["target_hi"]

                    all_markets.append(entry)
                    logger.info(f"  OK: {parsed['condition']} {parsed['target']}°{parsed['unit']} @ {yes_price:.3f}")

                except Exception as e:
                    logger.warning(f"  Erro ao parsear market: {e}")

        time.sleep(0.8)

    return all_markets
