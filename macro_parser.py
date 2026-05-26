"""
macro_parser.py — Busca e parse de mercados macro na Polymarket Gamma API.

Busca mercados de:
  - CPI (inflação mensal dos EUA)
  - NFP (empregos, desemprego)
  - Fed Rate (decisão FOMC)
  - GDP (PIB trimestral)

Diferente do gamma_parser.py (temperaturas), aqui os mercados são
identificados por palavras-chave no título, não por slugs de cidade.

Estratégia de edge:
  Para CPI: se o BLS publicou 3.8% e o mercado "3.7%" está em 0.15,
  apostamos NO em "3.7%" (que vai resolver 0) ou YES em "3.8%".
  A janela é de segundos a minutos antes do mercado atualizar o preço.
"""

import requests
import json
import time
import re
from datetime import datetime, timezone, timedelta

BASE_URL = "https://gamma-api.polymarket.com"
HEADERS  = {"User-Agent": "Mozilla/5.0"}

# =========================================================
# SLUGS E KEYWORDS POR TIPO DE MERCADO
# =========================================================

MACRO_SEARCH_TERMS = {
    "CPI": [
        "inflation us annual",
        "inflation us monthly",
        "cpi us",
        "consumer price index",
        "inflation annual",
    ],
    "NFP": [
        "nonfarm payrolls",
        "jobs report",
        "unemployment rate us",
        "nfp us",
        "payrolls",
    ],
    "FOMC": [
        "fed rate decision",
        "federal reserve rate",
        "fomc decision",
        "fed funds rate",
        "fed cut",
        "fed hold",
    ],
    "GDP": [
        "gdp us",
        "gdp growth",
        "gdp advance",
        "us gdp",
    ],
}

# =========================================================
# SAFE REQUEST
# =========================================================

def _safe_request(url, retries=3, timeout=15):
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                print("[macro_parser] Rate limit. Aguardando 60s...")
                time.sleep(60)
                continue
            print(f"[macro_parser] HTTP {r.status_code}: {url[:80]}")
        except Exception as e:
            print(f"[macro_parser] Erro (tentativa {attempt+1}): {e}")
        time.sleep(2 ** attempt)
    return None


# =========================================================
# BUSCA DE MERCADOS
# =========================================================

def _search_events(query, limit=10):
    """Busca eventos na Gamma API por texto."""
    url = f"{BASE_URL}/events?limit={limit}&active=true&q={requests.utils.quote(query)}"
    data = _safe_request(url)
    if not data or not isinstance(data, list):
        return []
    return data


def _parse_cpi_market(question, market):
    """
    Extrai info de mercados de CPI.
    Ex: "April Inflation US - Annual" com outcomes "3.7%", "3.8%", etc.
    """
    q = question.lower()
    if "inflation" not in q and "cpi" not in q:
        return None

    # Detecta mês de referência
    months = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
    }
    ref_month = None
    for name, num in months.items():
        if name in q:
            ref_month = num
            break

    # Detecta se é anual ou mensal
    is_annual  = "annual" in q or "yoy" in q or "year-over-year" in q
    is_monthly = "monthly" in q or "mom" in q or "month-over-month" in q

    # Extrai buckets dos outcomes
    outcomes = market.get("outcomes", "[]")
    if isinstance(outcomes, str):
        try:
            outcomes = json.loads(outcomes)
        except Exception:
            outcomes = []

    buckets = []
    for outcome in outcomes:
        # Padrão: "3.8%" ou "above 4.0%" ou "below 2.0%"
        match = re.search(r"(\d+(?:\.\d+)?)\s*%", str(outcome))
        if match:
            buckets.append({
                "label":   str(outcome),
                "value":   float(match.group(1)),
                "is_above": "above" in str(outcome).lower(),
                "is_below": "below" in str(outcome).lower(),
            })

    return {
        "type":      "CPI",
        "subtype":   "annual" if is_annual else "monthly",
        "ref_month": ref_month,
        "buckets":   buckets,
    }


def _parse_nfp_market(question, market):
    """Extrai info de mercados de empregos."""
    q = question.lower()
    if "payroll" not in q and "nfp" not in q and "jobs" not in q:
        return None

    outcomes = market.get("outcomes", "[]")
    if isinstance(outcomes, str):
        try:
            outcomes = json.loads(outcomes)
        except Exception:
            outcomes = []

    return {
        "type":     "NFP",
        "outcomes": outcomes,
    }


def _parse_fomc_market(question, market):
    """Extrai info de mercados de taxa do Fed."""
    q = question.lower()
    if "fed" not in q and "fomc" not in q and "federal reserve" not in q:
        return None

    outcomes = market.get("outcomes", "[]")
    if isinstance(outcomes, str):
        try:
            outcomes = json.loads(outcomes)
        except Exception:
            outcomes = []

    # Detecta decisão esperada nos outcomes
    decisions = []
    for outcome in outcomes:
        o = str(outcome).lower()
        if "cut" in o:
            decisions.append({"label": outcome, "type": "cut"})
        elif "hike" in o or "raise" in o or "increase" in o:
            decisions.append({"label": outcome, "type": "hike"})
        elif "hold" in o or "no change" in o or "unchanged" in o or "pause" in o:
            decisions.append({"label": outcome, "type": "hold"})
        else:
            # Pode ser um nível específico (ex: "3.50-3.75%")
            match = re.search(r"(\d+\.\d+)", str(outcome))
            if match:
                decisions.append({"label": outcome, "type": "level", "rate": float(match.group(1))})

    return {
        "type":      "FOMC",
        "decisions": decisions,
        "outcomes":  outcomes,
    }


# =========================================================
# FETCH PRINCIPAL
# =========================================================

def fetch_macro_markets(event_types=None, min_liquidity=500):
    """
    Busca mercados macro ativos na Polymarket.

    Args:
        event_types: lista de tipos a buscar, ex: ["CPI", "NFP", "FOMC"]
                     None = todos
        min_liquidity: volume mínimo para filtrar mercados ilíquidos

    Returns:
        Lista de dicts com mercados encontrados e parseados.
    """
    if event_types is None:
        event_types = list(MACRO_SEARCH_TERMS.keys())

    all_markets = []
    seen_ids = set()

    for event_type in event_types:
        search_terms = MACRO_SEARCH_TERMS.get(event_type, [])

        for term in search_terms:
            events = _search_events(term, limit=5)
            time.sleep(0.5)

            for event in events:
                event_title = (event.get("title") or event.get("name") or "").lower()

                # Relevância básica: pelo menos uma palavra-chave no título
                relevant = any(
                    kw in event_title
                    for kw in ["inflation", "cpi", "payroll", "nfp", "fed", "fomc", "gdp", "unemployment"]
                )
                if not relevant:
                    continue

                markets = event.get("markets", [])
                for market in markets:
                    market_id = str(market.get("id", ""))
                    if market_id in seen_ids or not market_id:
                        continue

                    question = market.get("question", "")

                    # Parse de preço
                    outcome_prices = market.get("outcomePrices")
                    if not outcome_prices:
                        continue
                    try:
                        if isinstance(outcome_prices, str):
                            prices = json.loads(outcome_prices)
                        else:
                            prices = list(outcome_prices)
                        yes_price = float(prices[0])
                        no_price  = float(prices[1]) if len(prices) > 1 else 1 - yes_price
                    except Exception:
                        continue

                    # Ignora mercados com preço inválido
                    if yes_price <= 0 or yes_price >= 1:
                        continue

                    # Spread saudável
                    if abs((yes_price + no_price) - 1.0) > 0.10:
                        continue

                    # Parse específico por tipo
                    parsed_info = None
                    if event_type == "CPI":
                        parsed_info = _parse_cpi_market(question, market)
                    elif event_type == "NFP":
                        parsed_info = _parse_nfp_market(question, market)
                    elif event_type == "FOMC":
                        parsed_info = _parse_fomc_market(question, market)

                    seen_ids.add(market_id)

                    all_markets.append({
                        "market_id":    market_id,
                        "event_type":   event_type,
                        "event_title":  event.get("title") or event.get("name", ""),
                        "question":     question,
                        "yes_price":    yes_price,
                        "no_price":     no_price,
                        "parsed":       parsed_info,
                        "outcomes":     market.get("outcomes"),
                        "end_date":     market.get("endDate") or market.get("end_date_iso"),
                        "volume":       float(market.get("volume", 0) or 0),
                    })

    print(f"[macro_parser] {len(all_markets)} mercados encontrados: {event_types}")
    return all_markets


# =========================================================
# IDENTIFICAÇÃO DE EDGE
# =========================================================

def find_edge_cpi(markets, cpi_data):
    """
    Dado o CPI real publicado, identifica mercados com edge.

    cpi_data: dict de get_cpi_latest()
    Retorna lista de oportunidades ordenadas por edge decrescente.
    """
    if not cpi_data:
        return []

    yoy = cpi_data.get("yoy")
    mom = cpi_data.get("mom")
    if yoy is None:
        return []

    opportunities = []

    for mkt in markets:
        if mkt["event_type"] != "CPI":
            continue

        parsed = mkt.get("parsed")
        if not parsed or not parsed.get("buckets"):
            continue

        question    = mkt["question"].lower()
        is_annual   = parsed.get("subtype") == "annual"
        real_value  = yoy if is_annual else mom
        if real_value is None:
            continue

        # Para cada bucket do mercado, verifica se o valor real cai nele
        for bucket in parsed["buckets"]:
            bucket_val   = bucket["value"]
            bucket_label = bucket["label"]
            is_above     = bucket.get("is_above", False)
            is_below     = bucket.get("is_below", False)

            # Lógica de resolução
            if is_above:
                resolves_yes = real_value > bucket_val
            elif is_below:
                resolves_yes = real_value < bucket_val
            else:
                # Bucket exato — ex: "3.8%"
                resolves_yes = abs(real_value - bucket_val) < 0.05

            yes_price   = mkt["yes_price"]
            model_prob  = 0.95 if resolves_yes else 0.05

            edge = model_prob - yes_price

            # Edge mínimo de 15% para valer a pena na janela de ineficiência
            if abs(edge) < 0.15:
                continue

            opportunities.append({
                "market_id":   mkt["market_id"],
                "question":    mkt["question"],
                "event_type":  "CPI",
                "bucket":      bucket_label,
                "real_value":  real_value,
                "resolves_yes": resolves_yes,
                "model_prob":  model_prob,
                "yes_price":   yes_price,
                "edge":        round(edge, 4),
                "trade_side":  "YES" if resolves_yes else "NO",
                "trade_price": yes_price if resolves_yes else (1 - yes_price),
            })

    return sorted(opportunities, key=lambda x: abs(x["edge"]), reverse=True)


def find_edge_fomc(markets, current_rate, actual_decision):
    """
    Dado a decisão real do FOMC, identifica mercados com edge.

    actual_decision: "hold", "cut_25", "cut_50", "hike_25", "hike_50"
    """
    opportunities = []

    for mkt in markets:
        if mkt["event_type"] != "FOMC":
            continue

        parsed = mkt.get("parsed")
        if not parsed:
            continue

        question_lower = mkt["question"].lower()

        # Mapeia decisão real para expectativa do mercado
        resolves_yes = None

        if actual_decision == "hold":
            resolves_yes = "hold" in question_lower or "no change" in question_lower or "pause" in question_lower
        elif actual_decision == "cut_25":
            resolves_yes = ("cut" in question_lower and "50" not in question_lower) or "25" in question_lower
        elif actual_decision == "cut_50":
            resolves_yes = "cut 50" in question_lower or "50bp" in question_lower or "50 bp" in question_lower
        elif actual_decision == "hike_25":
            resolves_yes = ("hike" in question_lower or "raise" in question_lower) and "50" not in question_lower

        if resolves_yes is None:
            continue

        yes_price  = mkt["yes_price"]
        model_prob = 0.95 if resolves_yes else 0.05
        edge       = model_prob - yes_price

        if abs(edge) < 0.15:
            continue

        opportunities.append({
            "market_id":   mkt["market_id"],
            "question":    mkt["question"],
            "event_type":  "FOMC",
            "resolves_yes": resolves_yes,
            "model_prob":  model_prob,
            "yes_price":   yes_price,
            "edge":        round(edge, 4),
            "trade_side":  "YES" if resolves_yes else "NO",
            "trade_price": yes_price if resolves_yes else (1 - yes_price),
        })

    return sorted(opportunities, key=lambda x: abs(x["edge"]), reverse=True)


# =========================================================
# TESTE
# =========================================================

if __name__ == "__main__":
    print("=" * 55)
    print("MACRO PARSER — BUSCANDO MERCADOS")
    print("=" * 55)

    markets = fetch_macro_markets(event_types=["CPI", "FOMC", "NFP"])

    for m in markets[:10]:
        print(
            f"\n  [{m['event_type']}] {m['question'][:60]}"
            f"\n      YES={m['yes_price']:.3f} | Vol=${m['volume']:.0f}"
        )
