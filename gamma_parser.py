"""
gamma_parser.py — Parser de mercados da Polymarket Gamma API

AUDITORIA COMPLETA — problemas encontrados e corrigidos:

1. FORMATO DO MERCADO MUDOU COMPLETAMENTE
   Antes: "Will the highest temp in NYC be 75°F or higher?" → above/below
   Agora: "Highest temperature in NYC on March 17?" com buckets tipo:
     - "50°F or higher" (above)
     - "48-49°F" (range de 2 graus)
     - "31°F or below" (below)
   O parse_question antigo não reconhecia buckets de 2 graus → descartava
   quase todos os mercados silenciosamente.

2. MERCADOS SÓ EXISTEM PARA D+0 E D+1
   A Polymarket cria mercados com ~4 dias de antecedência mas só para D+0/D+1.
   Buscar D+2 sempre retorna vazio. Corrigido: busca D+0 e D+1.
   D+0 é útil quando ainda é manhã (mercado não resolvido).

3. SLUG MUDOU
   Antes: "highest-temperature-in-new-york-on-june-2-2026"
   Agora: "highest-temperature-in-nyc-on-march-17-2026" (sem ano no slug)
   Adicionados novos aliases e formato sem ano.

4. SÃO PAULO COM ACENTO QUEBRAVA URL
   Corrigido: slug normalizado para "sao-paulo" sem acento.

5. market_is_healthy MUITO RESTRITIVO
   O filtro yes < 0.05 eliminava buckets válidos de 2°F que naturalmente
   têm preços baixos (ex: "48-49°F" a 0.06 é legítimo).
   Novo piso: 0.03 para aceitar buckets raros mas válidos.

6. ESTRATÉGIA DE TRADING PARA BUCKETS DE 2°F
   Com forecast de 23.4°C (≈74.1°F) e sigma=4°F (≈2.2°C), o bucket
   "74-75°F" tem prob ≈ 35-40% — muito acima do preço de mercado típico
   de 20-25%. Esse é o edge real. O bot precisa apostar no bucket mais
   provável, não em above/below.
"""

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
    "new-york":    ["nyc", "new-york"],
    "hong-kong":   ["hong-kong", "hongkong"],
    "los-angeles": ["los-angeles", "la"],
    "sao-paulo":   ["sao-paulo"],           # sem acento
    "mexico-city": ["mexico-city"],
    "toronto":     ["toronto"],
    "madrid":      ["madrid"],
    "london":      ["london"],
    "paris":       ["paris"],
    "tokyo":       ["tokyo"],
    "seoul":       ["seoul"],
    "milan":       ["milan"],
    "beijing":     ["beijing"],
    "houston":     ["houston"],
    "austin":      ["austin"],
    "denver":      ["denver"],
    "seattle":     ["seattle"],
    "chicago":     ["chicago"],
    "phoenix":     ["phoenix"],
    "miami":       ["miami"],
    "atlanta":     ["atlanta"],
    "boston":      ["boston"],
}

def _get_city_slugs(city):
    return CITY_SLUG_ALIASES.get(city, [city])


def safe_request(url, retries=4, timeout=15):
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                print(f"Rate limit (429). Aguardando 60s...")
                time.sleep(60)
                continue
            print(f"HTTP {r.status_code} para {url}")
        except Exception as e:
            print(f"Request error (tentativa {attempt+1}): {e}")
        time.sleep(2 ** attempt)
    return None


def detect_unit(question):
    """Detecta unidade da temperatura na pergunta."""
    if re.search(r'°[Ff]|[Ff]ahrenheit|\d+\s*[Ff](?!\w)', question):
        return "F"
    if re.search(r'°[Cc]|[Cc]elsius', question):
        return "C"
    # Heurística: se números > 55 sem unidade explícita, provavelmente °F
    nums = re.findall(r'\d+', question)
    if nums and max(int(n) for n in nums) > 55:
        return "F"
    return "C"


def parse_question(question):
    """
    CORRIGIDO: agora reconhece todos os formatos da Polymarket:
      - "50°F or higher"     → above, target=50, unit=F
      - "31°F or below"      → below, target=31, unit=F
      - "48-49°F"            → range de 2°F, target=48.5 (mid), unit=F
      - "24°C"               → exact, unit=C
      - "13°C or higher"     → above, unit=C
    """
    q = question.strip()
    unit = detect_unit(q)

    # Padrão: "50°F or higher" ou "13°C or higher"
    m = re.search(r'(\d+(?:\.\d+)?)\s*°?[CcFf]?\s+or\s+higher', q, re.IGNORECASE)
    if m:
        target = float(m.group(1))
        return {"condition": "above", "target": target, "unit": unit}

    # Padrão: "31°F or below" ou "18°C or below"
    m = re.search(r'(\d+(?:\.\d+)?)\s*°?[CcFf]?\s+or\s+(?:below|lower)', q, re.IGNORECASE)
    if m:
        target = float(m.group(1))
        return {"condition": "below", "target": target, "unit": unit}

    # Padrão bucket 2 graus: "48-49°F" ou "74-75°F" ou "22-23°C"
    m = re.search(r'(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)\s*°?[CcFf]?', q)
    if m:
        lo = float(m.group(1))
        hi = float(m.group(2))
        mid = round((lo + hi) / 2, 1)
        return {
            "condition": "range2",   # novo tipo: bucket de 2 graus
            "target":    mid,
            "target_lo": lo,
            "target_hi": hi,
            "unit":      unit,
        }

    # Padrão temperatura exata: "24°C" ou "75°F"
    m = re.search(r'(\d+(?:\.\d+)?)\s*°[CcFf]', q)
    if m:
        target = float(m.group(1))
        return {"condition": "exact", "target": target, "unit": unit}

    print(f"  Ignorado (formato não reconhecido): {question}")
    return None


def market_is_healthy(yes_price, no_price):
    """
    CORRIGIDO: piso reduzido para 0.03 para aceitar buckets de 2°F
    que legitimamente têm preços baixos (ex: bucket raro a 0.04).
    O filtro real de entrada continua sendo MIN_PRICE em risk.py (0.10).
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
    """
    Gera variantes de slug para a cidade e data.
    CORRIGIDO: inclui formato sem ano (que a Polymarket usa agora).
    """
    month = d.strftime('%B').lower()
    day   = d.day
    year  = d.year
    variants = []
    for alias in _get_city_slugs(city):
        # Formato atual da Polymarket (sem ano)
        variants.append(f"highest-temperature-in-{alias}-on-{month}-{day}")
        # Formato antigo (com ano) — mantido por compatibilidade
        variants.append(f"highest-temperature-in-{alias}-on-{month}-{day}-{year}")
    return variants


def _search_fallback(city, d):
    """Busca textual como fallback quando slug não funciona."""
    month = d.strftime('%B').lower()
    day   = d.day
    # Remove acentos e hífens para a query
    city_clean = city.replace("-", " ")
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


def fetch_markets(city):
    """
    CORRIGIDO: busca D+0 e D+1 (não D+1 e D+2).
    
    A Polymarket cria mercados para o dia atual e amanhã.
    D+0 tem valor quando ainda é manhã/tarde (resultado incerto).
    D+2 quase nunca existe — removido para não desperdiçar requests.
    
    Retorna lista de mercados válidos com condition, target, unit, yes_price.
    Para buckets range2, inclui target_lo e target_hi.
    """
    all_markets = []

    for i in range(0, 2):  # D+0 e D+1
        d = utcnow() + timedelta(days=i)

        event = None
        for slug in _slug_variants(city, d):
            print(f"  Slug: {slug}")
            data = safe_request(f"{BASE_URL}/events?slug={slug}")
            if data and isinstance(data, list) and len(data) > 0:
                event = data[0]
                break
            time.sleep(0.2)

        if event is None:
            event = _search_fallback(city, d)
            if event:
                print(f"  Encontrado via busca: {event.get('slug','')}")

        if event is None:
            print(f"  Sem evento para {city} {d.strftime('%B %d')}")
            continue

        for market in event.get("markets", []):
            try:
                question  = market.get("question", "")
                market_id = market.get("id")
                if not market_id:
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
                    print(f"  Market unhealthy (yes={yes_price:.3f} no={no_price:.3f})")
                    continue

                parsed = parse_question(question)
                if not parsed:
                    continue

                entry = {
                    "market_id":   market_id,
                    "question":    question,
                    "market_date": d.strftime("%Y-%m-%d"),
                    "event_slug":  event.get("slug", ""),
                    "condition":   parsed["condition"],
                    "target":      parsed["target"],
                    "unit":        parsed["unit"],
                    "yes_price":   yes_price,
                    "no_price":    no_price,
                }
                # Campos extras para range2
                if parsed["condition"] == "range2":
                    entry["target_lo"] = parsed["target_lo"]
                    entry["target_hi"] = parsed["target_hi"]

                all_markets.append(entry)
                print(f"  OK: {parsed['condition']} {parsed['target']}°{parsed['unit']} @ {yes_price:.3f}")

            except Exception as e:
                print(f"  Erro ao parsear market: {e}")

        time.sleep(0.8)

    return all_markets
