"""
migration.py
============
Migra o bankroll.json existente:
  1. Normaliza nomes de cidade ('Los-Angeles' → 'Los Angeles')
  2. Preenche campo 'ev' que estava null em trades antigos
  3. Detecta e reporta trades com unit='C' mas target suspeito (>55°C)
  4. Preenche 'fee' em trades WIN sem fee registrado

NÃO altera result, pnl ou stake — apenas normaliza metadados.

USO:
    python migration.py
"""

import json
import shutil
from datetime import datetime

BANKROLL_FILE = "bankroll.json"

# ==========================================
# HELPERS
# ==========================================

def normalize_city(city_raw):
    mapping = {
        "seoul":       "Seoul",
        "tokyo":       "Tokyo",
        "los-angeles": "Los Angeles",
        "los angeles": "Los Angeles",
        "losangeles":  "Los Angeles",
        "london":      "London",
        "paris":       "Paris",
    }
    key = city_raw.lower().replace("-", " ").replace("_", " ").strip()
    return mapping.get(key, city_raw)

def calc_ev(model_prob, market_price):
    if not model_prob or not market_price or market_price <= 0:
        return None
    return round(float(model_prob) / float(market_price) - 1.0, 4)

def calc_fee(stake, market_price, polymarket_fee=0.02):
    if not stake or not market_price or market_price <= 0:
        return None
    gross = float(stake) / float(market_price)
    return round((gross - float(stake)) * polymarket_fee, 4)

# ==========================================
# MAIN
# ==========================================

def run_migration():

    with open(BANKROLL_FILE, "r") as f:
        bankroll = json.load(f)

    history = bankroll["history"]

    # Backup antes de qualquer alteração
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_file = f"bankroll_pre_migration_{ts}.json"
    shutil.copy2(BANKROLL_FILE, backup_file)
    print(f"Backup salvo: {backup_file}")

    n_city     = 0
    n_ev       = 0
    n_fee      = 0
    n_suspect  = 0

    print(f"\nMigrando {len(history)} trades...\n")

    for i, trade in enumerate(history):

        # 1. Normaliza cidade
        city_raw = trade.get("city", "")
        city_norm = normalize_city(city_raw)
        if city_norm != city_raw:
            print(f"  [{i+1}] Cidade: '{city_raw}' → '{city_norm}'")
            trade["city"] = city_norm
            n_city += 1

        # 2. Preenche EV se ausente ou inválido
        ev_raw = trade.get("ev")
        if ev_raw is None or ev_raw == "?" or ev_raw == 0:
            ev = calc_ev(trade.get("model_prob"), trade.get("market_price"))
            if ev is not None:
                trade["ev"] = ev
                n_ev += 1

        # 3. Detecta targets suspeitos (>55°C com unit=C)
        unit   = trade.get("unit", "C")
        target = trade.get("target")
        if unit == "C" and target is not None and float(target) > 55:
            print(
                f"  [{i+1}] SUSPEITO: {trade.get('city')} | {trade.get('market_date')} | "
                f"target={target}°C (provável Fahrenheit) | result={trade.get('result')} | pnl={trade.get('pnl')}"
            )
            n_suspect += 1

        # 4. Preenche fee em trades WIN sem fee
        if trade.get("result") == "WIN" and trade.get("fee") is None:
            fee = calc_fee(trade.get("stake"), trade.get("market_price"))
            if fee is not None:
                trade["fee"] = fee
                n_fee += 1

        # 5. Garante campos padrão existam
        trade.setdefault("fee", 0.0)
        trade.setdefault("real_temp_c", None)
        trade.setdefault("forecast_day", None)

    with open(BANKROLL_FILE, "w") as f:
        json.dump(bankroll, f, indent=4)

    print("\n====================")
    print("MIGRATION COMPLETA")
    print("====================")
    print(f"Cidades normalizadas: {n_city}")
    print(f"EV preenchidos:       {n_ev}")
    print(f"Fees preenchidas:     {n_fee}")
    print(f"Targets suspeitos:    {n_suspect}")
    print(f"Backup:               {backup_file}")

    if n_suspect > 0:
        print(
            f"\nATENÇÃO: {n_suspect} trade(s) com target suspeito (>55°C com unit=C).\n"
            "Esses trades podem ter sido calculados com unidade errada.\n"
            "Os resultados foram mantidos, mas revise manualmente."
        )


if __name__ == "__main__":
    run_migration()
