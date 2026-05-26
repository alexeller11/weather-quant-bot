"""
macro_data.py — Leitura de dados macroeconômicos via APIs públicas gratuitas.

Fontes:
  - BLS API v2 (gratuita, sem chave para séries básicas)
    https://api.bls.gov/publicAPI/v2/timeseries/data/
  - FRED API (St. Louis Fed) — gratuita com chave opcional
    https://fred.stlouisfed.org/docs/api/fred/
  - BEA API (Bureau of Economic Analysis) — gratuita com chave
    https://apps.bea.gov/api/

Estratégia:
  - CPI:  lê CUSR0000SA0 (CPI-U All Items SA) direto do BLS
  - NFP:  lê CES0000000001 (Total Nonfarm) + LNS14000000 (Unemployment)
  - FOMC: lê DFEDTARU (Fed Funds Target Upper) do FRED
  - GDP:  lê GDPC1 (Real GDP) do BEA/FRED

Para cada dado, calcula YoY, MoM, e identifica o bucket da Polymarket.
"""

import requests
import json
import time
from datetime import datetime, timezone, timedelta, date

# =========================================================
# SÉRIES BLS
# =========================================================

BLS_SERIES = {
    "CPI_ALL":       "CUSR0000SA0",    # CPI-U All Items Seasonally Adjusted
    "CPI_CORE":      "CUSR0000SA0L1E", # CPI Core (ex food & energy)
    "NFP_TOTAL":     "CES0000000001",  # Nonfarm payrolls (thousands)
    "UNEMPLOYMENT":  "LNS14000000",    # Unemployment rate (%)
}

BLS_API_BASE = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
FRED_API_BASE = "https://fred.stlouisfed.org/graph/fredgraph.csv"

HEADERS = {
    "User-Agent": "WeatherQuantBot/1.0 (research@example.com)",
    "Content-Type": "application/json",
}

# =========================================================
# BLS — LEITURA DIRETA
# =========================================================

def _fetch_bls_series(series_ids, start_year=None, end_year=None):
    """
    Busca uma ou mais séries BLS via API pública (sem chave).
    Retorna dict {series_id: [(year, period, value), ...]}
    """
    if start_year is None:
        start_year = datetime.now().year - 1
    if end_year is None:
        end_year = datetime.now().year

    payload = {
        "seriesid":  series_ids,
        "startyear": str(start_year),
        "endyear":   str(end_year),
    }

    try:
        r = requests.post(
            BLS_API_BASE,
            json=payload,
            headers=HEADERS,
            timeout=20,
        )
        if r.status_code != 200:
            print(f"[macro_data] BLS HTTP {r.status_code}")
            return {}

        data = r.json()

        if data.get("status") != "REQUEST_SUCCEEDED":
            msg = data.get("message", ["erro desconhecido"])
            print(f"[macro_data] BLS status: {data.get('status')} | {msg}")
            return {}

        result = {}
        for series in data.get("Results", {}).get("series", []):
            sid  = series["seriesID"]
            rows = []
            for item in series.get("data", []):
                try:
                    period = item["period"]    # "M01" ... "M12"
                    year   = int(item["year"])
                    value  = float(item["value"])
                    rows.append((year, period, value))
                except Exception:
                    continue
            result[sid] = sorted(rows, key=lambda x: (x[0], x[1]), reverse=True)

        return result

    except Exception as e:
        print(f"[macro_data] BLS erro: {e}")
        return {}


def _period_to_month(period_str):
    """'M05' → 5"""
    return int(period_str.replace("M", "").replace("A", "0"))


# =========================================================
# CPI
# =========================================================

def get_cpi_latest():
    """
    Retorna dado mais recente de CPI.

    Returns dict:
        {
            "value":      315.605,   # índice absoluto
            "yoy":        3.8,       # variação anual %
            "mom":        0.6,       # variação mensal %
            "month":      4,         # mês de referência
            "year":       2026,
            "release_date": "2026-05-12",
            "source":     "BLS",
        }
    """
    series_ids = [BLS_SERIES["CPI_ALL"]]
    now_year   = datetime.now().year
    data       = _fetch_bls_series(series_ids, start_year=now_year - 1, end_year=now_year)

    rows = data.get(BLS_SERIES["CPI_ALL"], [])
    if len(rows) < 13:
        print(f"[macro_data] CPI: dados insuficientes ({len(rows)} pontos)")
        return None

    # Mais recente
    latest_year, latest_period, latest_val = rows[0]
    latest_month = _period_to_month(latest_period)

    # 12 meses atrás
    prev_rows = [
        r for r in rows
        if r[0] == latest_year - 1 and r[1] == latest_period
    ]
    if not prev_rows:
        print("[macro_data] CPI: sem dado YoY")
        return None
    _, _, yoy_base = prev_rows[0]

    # Mês anterior
    prev_month_rows = [
        r for r in rows
        if not (r[0] == latest_year and r[1] == latest_period)
    ]
    if not prev_month_rows:
        return None
    _, _, mom_base = prev_month_rows[0]

    yoy = round((latest_val / yoy_base - 1) * 100, 2)
    mom = round((latest_val / mom_base - 1) * 100, 2)

    print(
        f"[macro_data] CPI: {latest_val:.3f} | "
        f"YoY={yoy:+.1f}% | MoM={mom:+.1f}% | "
        f"{latest_month}/{latest_year}"
    )

    return {
        "value":    latest_val,
        "yoy":      yoy,
        "mom":      mom,
        "month":    latest_month,
        "year":     latest_year,
        "source":   "BLS",
    }


# =========================================================
# NFP
# =========================================================

def get_nfp_latest():
    """
    Retorna dado mais recente de empregos.

    Returns dict:
        {
            "nfp":          189,     # variação mensal em milhares
            "unemployment": 4.1,     # taxa de desemprego %
            "month":        4,
            "year":         2026,
            "source":       "BLS",
        }
    """
    series_ids = [BLS_SERIES["NFP_TOTAL"], BLS_SERIES["UNEMPLOYMENT"]]
    now_year   = datetime.now().year
    data       = _fetch_bls_series(series_ids, start_year=now_year - 1, end_year=now_year)

    nfp_rows  = data.get(BLS_SERIES["NFP_TOTAL"], [])
    unemp_rows = data.get(BLS_SERIES["UNEMPLOYMENT"], [])

    if not nfp_rows or not unemp_rows:
        print("[macro_data] NFP: dados insuficientes")
        return None

    latest_nfp_year, latest_nfp_period, latest_nfp = nfp_rows[0]
    latest_month = _period_to_month(latest_nfp_period)

    # NFP é level absoluto — calcular variação mensal
    if len(nfp_rows) < 2:
        return None
    _, _, prev_nfp = nfp_rows[1]
    nfp_change = round(latest_nfp - prev_nfp, 0)

    # Taxa de desemprego
    unemp_latest = [
        r for r in unemp_rows
        if r[0] == latest_nfp_year and r[1] == latest_nfp_period
    ]
    unemployment = unemp_latest[0][2] if unemp_latest else None

    print(
        f"[macro_data] NFP: {nfp_change:+.0f}k | "
        f"Desemprego: {unemployment}% | "
        f"{latest_month}/{latest_nfp_year}"
    )

    return {
        "nfp":          int(nfp_change),
        "unemployment": unemployment,
        "month":        latest_month,
        "year":         latest_nfp_year,
        "source":       "BLS",
    }


# =========================================================
# FOMC — via FRED CSV (sem chave necessária para basic)
# =========================================================

def get_fomc_rate():
    """
    Retorna taxa atual do Fed Funds Target (upper bound) via FRED.
    """
    try:
        r = requests.get(
            FRED_API_BASE,
            params={"id": "DFEDTARU"},
            timeout=15,
        )
        if r.status_code != 200:
            print(f"[macro_data] FRED HTTP {r.status_code}")
            return None

        lines = r.text.strip().split("\n")
        # Formato: DATE,VALUE
        # Pula header
        data_rows = []
        for line in lines[1:]:
            parts = line.split(",")
            if len(parts) == 2:
                try:
                    val = float(parts[1])
                    data_rows.append((parts[0], val))
                except Exception:
                    continue

        if not data_rows:
            return None

        # Mais recente
        latest_date, latest_rate = data_rows[-1]

        print(f"[macro_data] FOMC Fed Rate Upper: {latest_rate}% ({latest_date})")

        return {
            "rate":   latest_rate,
            "date":   latest_date,
            "source": "FRED",
        }

    except Exception as e:
        print(f"[macro_data] FOMC erro: {e}")
        return None


# =========================================================
# IDENTIFICAÇÃO DE BUCKET POLYMARKET
# =========================================================

def identify_cpi_bucket(yoy_pct):
    """
    Dado CPI YoY%, retorna qual bucket da Polymarket corresponde.

    Mercados típicos na Polymarket:
      "April Inflation US - Annual"
      Buckets: 3.5%, 3.6%, 3.7%, 3.8%, 3.9%, 4.0%, etc.

    Retorna string do bucket (ex: "3.8%") e lista de buckets adjacentes.
    """
    rounded = round(yoy_pct, 1)
    bucket  = f"{rounded:.1f}%"

    # Buckets adjacentes (o mercado pode ter ±0.1% como alternativas)
    adj_down = f"{round(rounded - 0.1, 1):.1f}%"
    adj_up   = f"{round(rounded + 0.1, 1):.1f}%"

    return {
        "bucket_exact":   bucket,
        "bucket_low":     adj_down,
        "bucket_high":    adj_up,
        "value":          yoy_pct,
        "rounded":        rounded,
    }


def identify_nfp_bucket(nfp_change_k):
    """
    NFP change em milhares → bucket da Polymarket.
    Ex: +189k → "150k-200k" ou "above 150k"
    """
    buckets = [
        (0,    "below 0k (perda de empregos)"),
        (50,   "0-50k"),
        (100,  "50-100k"),
        (150,  "100-150k"),
        (200,  "150-200k"),
        (250,  "200-250k"),
        (300,  "250-300k"),
        (999,  "above 300k"),
    ]

    for threshold, label in buckets:
        if nfp_change_k < threshold:
            return {"bucket": label, "value": nfp_change_k}

    return {"bucket": "above 300k", "value": nfp_change_k}


def identify_fed_rate_bucket(current_rate, expected_decision):
    """
    expected_decision: "hold", "cut_25", "cut_50", "hike_25", "hike_50"
    Retorna taxa esperada após decisão.
    """
    decisions = {
        "hold":    0.00,
        "cut_25":  -0.25,
        "cut_50":  -0.50,
        "hike_25": +0.25,
        "hike_50": +0.50,
    }
    delta = decisions.get(expected_decision, 0.0)
    new_rate = round(current_rate + delta, 2)
    return {
        "current":  current_rate,
        "expected": new_rate,
        "decision": expected_decision,
        "delta":    delta,
    }


# =========================================================
# TESTE
# =========================================================

if __name__ == "__main__":
    print("=" * 55)
    print("MACRO DATA — TESTE DE FONTES")
    print("=" * 55)

    print("\n[CPI]")
    cpi = get_cpi_latest()
    if cpi:
        bucket = identify_cpi_bucket(cpi["yoy"])
        print(f"  Bucket Polymarket: {bucket['bucket_exact']}")
        print(f"  Adjacentes: {bucket['bucket_low']} | {bucket['bucket_high']}")

    print("\n[NFP]")
    nfp = get_nfp_latest()
    if nfp:
        bucket = identify_nfp_bucket(nfp["nfp"])
        print(f"  Bucket Polymarket: {bucket['bucket']}")

    print("\n[FOMC]")
    fomc = get_fomc_rate()
    if fomc:
        print(f"  Taxa atual: {fomc['rate']}%")

    print("\n" + "=" * 55)
