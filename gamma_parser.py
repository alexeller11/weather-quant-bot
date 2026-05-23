import requests
import re
import time
import json
from datetime import datetime, timedelta, timezone

def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)

BASE_URL = "https://gamma-api.polymarket.com"
HEADERS  = {"User-Agent": "Mozilla/5.0"}

# ==========================================
# SAFE REQUEST — com tratamento de 429
# ==========================================

def safe_request(url, retries=5, timeout=15):
    """
    Diferencia HTTP 429 (rate limit) dos demais erros.
    Em 429 espera 60s antes de tentar de novo.
    """
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

# ==========================================
# DETECÇÃO DE UNIDADE
# ==========================================

def detect_unit(question):
    """
    Detecta se a pergunta usa Fahrenheit ou Celsius.
    Prioridade: °F > número+F em contexto > Fahrenheit > °C > Celsius > default C.
    """
    q = question.lower()
    
    # Padrões Fahrenheit com contexto (para evitar falsos positivos)
    fahrenheit_patterns = [
        r"°[Ff]",  # °F ou °f
        r"(?:temperature|temp|be|reach|hit)\s+\d+\s*[Ff](?![a-z])",  # "temperature 60F" mas não "far"
        r"\d+\s*[Ff](?:\s|,|\?|$)",  # "60F " (espaço após)
        r"[Ff]ahrenheit",
    ]
    
    for pattern in fahrenheit_patterns:
        if re.search(pattern, question):
            return "F"

    # Padrões Celsius
    celsius_patterns = [
        r"°[Cc]",
        r"[Cc]elsius"
    ]
    
    for pattern in celsius_patterns:
        if re.search(pattern, question):
            return "C"

    return "C"

# ==========================================
# EXTRAI NÚMERO DA TEMPERATURA
# ==========================================

def _extract_temp_candidates(question, unit):
    """
    Extrai candidatos de temperatura da pergunta, filtrando
    números que são claramente datas (dias do mês ≤ 31 em contexto de data).
    """
    if unit == "F":
        # Tenta colado com unidade primeiro
        attached = re.findall(r"(\d+(?:\.\d+)?)\s*(?:°[Ff]|[Ff](?![a-z]))", question)
        if attached:
            return [float(n) for n in attached if 50 <= float(n) <= 130]
        # Fallback: range razoável de Fahrenheit
        return [float(n) for n in re.findall(r"\d+(?:\.\d+)?", question)
                if 50 <= float(n) <= 130]
    else:
        # Tenta colado com grau primeiro
        attached = re.findall(r"(\d+(?:\.\d+)?)\s*°[Cc]", question)
        if attached:
            return [float(n) for n in attached if -10 <= float(n) <= 55]
        # Fallback: range razoável de Celsius, excluindo dias do mês isolados
        candidates = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", question)
                      if 10 <= float(n) <= 55]
        # Se houver candidatos acima de 31, prefira eles (dias do mês ≤ 31)
        non_day = [n for n in candidates if n > 31]
        return non_day if non_day else candidates

# ==========================================
# PARSE QUESTION
# ==========================================

def parse_question(question):
    """
    Extrai condição, target e unidade da pergunta do mercado.

    Suporta três formatos que a Polymarket usa:
      1. "22°C or higher"  → condition=above, target=22
      2. "Will ... be 22°C"  → condition=exact, target=22
      3. "between 74-75°F"   → condition=range, target_low=74, target_high=75

    Retorna dict {condition, target, [target_high], unit} ou None.
    """
    q = question.lower()
    unit = detect_unit(question)

    # ── Formato 1: "or higher" / "or above" / "or lower" / "or below" ──────
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

    # ── Formato 2: "between X-Y" ou "between X and Y" ───────────────────────
    # FIX #4: Corrigir regex
    range_match = re.search(
        r"between\s+(\d+(?:\.\d+)?)\s*(?:[-–]|and)\s*(\d+(?:\.\d+)?)", q
    )
    if range_match:
        low  = float(range_match.group(1))
        high = float(range_match.group(2))
        # Verifica range razoável
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

    # ── Formato 3: temperatura exata — "Will ... be 22°C" ───────────────────
    # Detecta "be <número><unidade>" ou apenas um número de temperatura isolado
    # Só aceita se tiver número colado com unidade ou grau, para evitar falsos positivos
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

# ==========================================
# HEALTH CHECK
# ==========================================

def market_is_healthy(yes_price, no_price):
    try:
        yes_price = float(yes_price)
        no_price  = float(no_price)
    except Exception:
        return False

    if yes_price <= 0 or yes_price >= 1:
        return False

    # Yes + No devem somar perto de 1 (spread max 8%)
    if abs((yes_price + no_price) - 1.0) > 0.08:
        return False

    return True

# ==========================================
# FETCH MARKETS
# ==========================================

def _slug_variants(city, d):
    """
    Gera variantes de slug para uma cidade e data.
    A Polymarket às vezes usa formatos ligeiramente diferentes ao longo do tempo.
    """
    month = d.strftime('%B').lower()
    day   = d.day
    year  = d.year
    variants = [
        f"highest-temperature-in-{city}-on-{month}-{day}-{year}",
        f"highest-temperature-in-{city}-on-{month}-{day}",
    ]
    return variants


def _search_fallback(city, d):
    """
    Quando o slug não retorna resultado, tenta buscar via
    endpoint /events com query de texto.
    Retorna o event dict ou None.
    """
    month = d.strftime('%B').lower()
    day   = d.day
    query = f"highest temperature {city} {month} {day}"
    url   = f"{BASE_URL}/events?limit=5&active=true&q={requests.utils.quote(query)}"
    data  = safe_request(url)
    if not data or not isinstance(data, list):
        return None
    city_clean = city.replace("-", " ")
    for event in data:
        title = (event.get("title") or event.get("name") or "").lower()
        if city_clean in title and month[:3] in title:
            return event
    return None


def fetch_markets(city):
    """
    Busca mercados de temperatura para a cidade nos próximos 3 dias.

    Tenta múltiplas variantes de slug e, se todas falharem,
    usa busca por texto como fallback.
    """
    all_markets = []

    for i in range(3):
        d = utcnow() + timedelta(days=i)

        event = None

        # Tenta variantes de slug
        for slug in _slug_variants(city, d):
            print(f"  Slug: {slug}")
            data = safe_request(f"{BASE_URL}/events?slug={slug}")
            if data and isinstance(data, list) and len(data) > 0:
                event = data[0]
                break
            time.sleep(0.3)

        # Fallback: busca por texto
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
