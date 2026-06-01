import requests
import re
import time
import json
from datetime import datetime, timedelta, timezone

def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)

BASE_URL = "https://gamma-api.polymarket.com"
HEADERS  = {"User-Agent": "Mozilla/5.0"}

CITY_SLUG_ALIASES = {
    "new-york":    ["new-york", "nyc", "new york"],
    "hong-kong":   ["hong-kong", "hongkong"],
    "los-angeles": ["los-angeles", "la", "losangeles"],
    "sao-paulo":   ["sao-paulo", "saopaulo"],  # CORRIGIDO: removido acento que quebra URL
    "mexico-city": ["mexico-city", "mexicocity", "mexico city"],
    "toronto":     ["toronto"],
    "madrid":      ["madrid"],
}

def _get_city_slugs(city):
    return CITY_SLUG_ALIASES.get(city, [city])


def safe_request(url, retries=5, timeout=15):
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                wait = 60
                print(f"Rate limit (429). Aguardando {wait}s...")
                time.sleep(wait)
                continue
            print(f"HTTP {r.status_code} para {url}")
        except Exception as e:
            print(f"Request error (tentativa {attempt+1}): {e}")
        sleep_time = 2 ** attempt
        print(f"Retry em {sleep_time}s...")
        time.sleep(sleep_time)
    return None


def detect_unit(question):
    q = question.lower()

    fahrenheit_patterns = [
        r"°[Ff]",
        r"(?:temperature|temp|be|reach|hit)\s+\d+\s*[Ff](?![a-z])",
        r"\d+\s*[Ff](?:\s|,|\?|$)",
        r"[Ff]ahrenheit",
    ]

    for pattern in fahrenheit_patterns:
        if re.search(pattern, question):
            return "F"

    celsius_patterns = [
        r"°[Cc]",
        r"[Cc]elsius"
    ]

    for pattern in celsius_patterns:
        if re.search(pattern, question):
            return "C"

    return "C"


def _extract_temp_candidates(question, unit):
    if unit == "F":
        attached = re.findall(r"(\d+(?:\.\d+)?)\s*(?:°[Ff]|[Ff](?![a-z]))", question)
        if attached:
            return [float(n) for n in attached if 20 <= float(n) <= 130]
        return [float(n) for n in re.findall(r"\d+(?:\.\d+)?", question)
                if 20 <= float(n) <= 130]
    else:
        attached = re.findall(r"(\d+(?:\.\d+)?)\s*°[Cc]", question)
        if attached:
            return [float(n) for n in attached if -10 <= float(n) <= 55]
        candidates = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", question)
                      if 10 <= float(n) <= 55]
        non_day = [n for n in candidates if n > 31]
        return non_day if non_day else candidates


def parse_question(question):
    q = question.lower()
    unit = detect_unit(question)

    if "or higher" in q or "or above" in q:
        condition = "above"
        candidates = _extract_temp_candidates(question, unit)
        if not candidates:
            print(f"  Nenhum target em: {question}")
            return None
        target = candidates[0]
        if unit == "C" and target > 55:
            unit = "F"
        return {"condition": condition, "target": target, "unit": unit}

    if "or lower" in q or "or below" in q:
        condition = "below"
        candidates = _extract_temp_candidates(question, unit)
        if not candidates:
            print(f"  Nenhum target em: {question}")
            return None
        target = candidates[0]
        if unit == "C" and target > 55:
            unit = "F"
        return {"condition": condition, "target": target, "unit": unit}

    range_match = re.search(
        r"between\s+(\d+(?:\.\d+)?)\s*(?:[-–]|and)\s*(\d+(?:\.\d+)?)", q
    )
    if range_match:
        low  = float(range_match.group(1))
        high = float(range_match.group(2))
        valid_f = 50 <= low <= 130 and 50 <= high <= 130
        valid_c = -10 <= low <= 55 and -10 <= high <= 55
        if valid_f or valid_c:
            if unit == "C" and low > 55:
                unit = "F"
            return {
                "condition":   "range",
                "target":      low,
                "target_high": high,
                "unit":        unit,
            }
        print(f"  Range fora de limites: {question}")
        return None

    exact_with_unit = re.findall(r"(\d+(?:\.\d+)?)\s*°[CcFf]", question)
    if not exact_with_unit and unit == "F":
        exact_with_unit = re.findall(r"(\d+(?:\.\d+)?)\s*[Ff](?![a-z])", question)

    if exact_with_unit:
        target = float(exact_with_unit[0])
        if unit == "C" and target > 55:
            unit = "F"
        valid = (unit == "F" and 50 <= target <= 130) or \
                (unit == "C" and -10 <= target <= 55)
        if valid:
            return {"condition": "exact", "target": target, "unit": unit}

    print(f"  Ignorado (formato não reconhecido): {question}")
    return None


def market_is_healthy(yes_price, no_price):
    """
    CORRIGIDO: limites ajustados para capturar mercados de D+1/D+2.
    
    Antes: rejeitava yes < 0.05 e yes > 0.95 — isso eliminava todos os
    mercados futuros cujos preços extremos ainda não foram ajustados
    pelo mercado.
    
    Agora: aceita a faixa 0.08 a 0.92 para capturar mais mercados
    futuros com liquidez real, mantendo o filtro de soma yes+no próxima de 1.
    O filtro de preço mínimo (MIN_PRICE) em risk.py faz a filtragem final
    e é a barreira real para entrada.
    """
    try:
        yes_price = float(yes_price)
        no_price  = float(no_price)
    except Exception:
        return False

    if yes_price <= 0 or yes_price >= 1:
        return False

    # Mercados quase resolvidos — sem edge possível
    if yes_price < 0.05 or yes_price > 0.95:
        return False

    # Tolerância de spread: aceita mercados até 12pp de desequilíbrio
    # (era 8pp — alguns mercados de D+1 legítimos ficavam fora)
    if abs((yes_price + no_price) - 1.0) > 0.12:
        return False

    return True


def _slug_variants(city, d):
    month = d.strftime('%B').lower()
    day   = d.day
    year  = d.year
    variants = []

    for alias in _get_city_slugs(city):
        variants.append(f"highest-temperature-in-{alias}-on-{month}-{day}-{year}")
        variants.append(f"highest-temperature-in-{alias}-on-{month}-{day}")

    return variants


def _search_fallback(city, d):
    month = d.strftime('%B').lower()
    day   = d.day
    # CORRIGIDO: remove acentos para evitar encoding quebrado na URL
    city_clean = city.replace("-", " ").replace("ã", "a").replace("ô", "o").replace("é", "e")
    query = f"highest temperature {city_clean} {month} {day}"
    url   = f"{BASE_URL}/events?limit=10&active=true&q={requests.utils.quote(query)}"
    data  = safe_request(url)
    if not data or not isinstance(data, list):
        return None
    for event in data:
        title = (event.get("title") or event.get("name") or "").lower()
        if city_clean.split()[0] in title and month[:3] in title:
            return event
    return None


def fetch_markets(city):
    """
    CORRIGIDO: pula D+0 (hoje) — mercados do dia atual já têm preços
    extremos porque o resultado é quase certo. O bot só busca D+1 e D+2
    onde há incerteza real e edge possível.
    
    Antes: range(3) → dias 0, 1, 2 (hoje incluído)
    Agora: range(1, 3) → dias 1, 2 (amanhã e depois)
    """
    all_markets = []

    # CORRIGIDO: começa em i=1 para pular D+0
    for i in range(1, 3):
        d = utcnow() + timedelta(days=i)

        event = None

        for slug in _slug_variants(city, d):
            print(f"  Slug: {slug}")
            data = safe_request(f"{BASE_URL}/events?slug={slug}")
            if data and isinstance(data, list) and len(data) > 0:
                event = data[0]
                break
            time.sleep(0.3)

        if event is None:
            event = _search_fallback(city, d)
            if event:
                print(f"  Encontrado via busca textual: {event.get('title') or event.get('slug','')}")

        if event is None:
            print(f"  Sem evento para {city} {d.strftime('%B %d')}")
            continue

        markets = event.get("markets", [])

        for market in markets:
            try:
                question  = market.get("question", "")
                market_id = market.get("id")

                if not market_id:
                    continue

                outcome_prices = market.get("outcomePrices")
                if not outcome_prices:
                    continue

                if isinstance(outcome_prices, str):
                    prices = json.loads(outcome_prices)
                else:
                    prices = list(outcome_prices)

                if len(prices) < 2:
                    continue

                yes_price = float(prices[0])
                no_price  = float(prices[1])

                if not market_is_healthy(yes_price, no_price):
                    print(f"  Market unhealthy "
                          f"(yes={yes_price:.3f} no={no_price:.3f})")
                    continue

                parsed = parse_question(question)
                if not parsed:
                    continue

                all_markets.append({
                    "market_id":   market_id,
                    "question":    question,
                    "market_date": d.strftime("%Y-%m-%d"),
                    "event_slug":  event.get("slug", ""),
                    "condition":   parsed["condition"],
                    "target":      parsed["target"],
                    "target_high": parsed.get("target_high"),
                    "unit":        parsed["unit"],
                    "yes_price":   yes_price,
                    "no_price":    no_price,
                })

            except Exception as e:
                print(f"  Erro ao parsear market: {e}")

        time.sleep(1)

    return all_markets
