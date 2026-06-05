#!/usr/bin/env python3
"""
corrigir_bankroll.py — Corrige 3 trades liquidados incorretamente pelo
settlement v5.4 (antes da correção da lógica NO em v5.5).

CORREÇÕES:
  2407026_NO  Miami BELOW 85°F NO:
    real=26.6°C=79.9°F < 85°F → YES ganhou → NO PERDEU
    WIN +$0.26 → LOSS -$3.94

  2399701_NO  Toronto EXACT 25°C NO:
    real=24.9°C, |24.9-25.0|=0.1 ≤ 0.5 → YES ganhou → NO PERDEU
    WIN +$2.88 → LOSS -$3.92

  2406981_NO  Toronto ABOVE 28°C NO:
    real=27.5°C < 28.0°C → YES PERDEU → NO GANHOU
    LOSS -$3.99 → WIN +$14.63

Saldo: $199.55 → $207.17
"""

import os, json, sys
from datetime import datetime, timezone

DATABASE_URL = os.environ.get("DATABASE_URL", "")

CORRECOES = {
    "2407026_NO": {
        "city": "Miami BELOW 85°F NO",
        "result_novo": "LOSS",
        "pnl_novo": -3.94,
        "fee_novo": 0.0,
        "motivo": "real=26.6°C=79.9°F < 85°F → YES ganhou → NO perdeu",
    },
    "2399701_NO": {
        "city": "Toronto EXACT 25°C NO",
        "result_novo": "LOSS",
        "pnl_novo": -3.92,
        "fee_novo": 0.0,
        "motivo": "real=24.9°C, |24.9-25.0|=0.1 ≤ 0.5°C → YES ganhou → NO perdeu",
    },
    "2406981_NO": {
        "city": "Toronto ABOVE 28°C NO",
        "result_novo": "WIN",
        "pnl_novo": 14.63,
        "fee_novo": 0.38,
        "motivo": "real=27.5°C < 28.0°C → YES perdeu → NO ganhou (stake/0.21 - stake - fee)",
    },
}

def aplicar_correcoes(data):
    history = data.get("history", [])
    saldo = float(data.get("balance", 0))
    aplicados = 0

    for trade in history:
        mid = trade.get("market_id", "")
        if mid not in CORRECOES:
            continue
        if trade.get("correcao_v55"):
            print(f"  {mid}: já corrigido, pulando")
            continue

        c = CORRECOES[mid]
        pnl_antigo = float(trade.get("pnl", 0))
        diff = c["pnl_novo"] - pnl_antigo

        print(f"\n  [{mid}] {c['city']}")
        print(f"  Motivo: {c['motivo']}")
        print(f"  result: {trade.get('result')} → {c['result_novo']}")
        print(f"  pnl:    ${pnl_antigo:+.4f} → ${c['pnl_novo']:+.4f}  (diff ${diff:+.4f})")

        saldo = round(saldo + diff, 4)
        trade["result"]       = c["result_novo"]
        trade["pnl"]          = c["pnl_novo"]
        trade["fee"]          = c["fee_novo"]
        trade["correcao_v55"] = c["motivo"]
        trade["exit_time"]    = trade.get("exit_time") or datetime.now(timezone.utc).isoformat()

        print(f"  Saldo parcial: ${saldo:.4f}")
        aplicados += 1

    data["balance"] = saldo
    return data, aplicados

def carregar_postgres():
    if not DATABASE_URL:
        return None
    try:
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL, sslmode="require")
        with conn.cursor() as cur:
            cur.execute("SELECT data FROM bankroll ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
        conn.close()
        if row:
            print("Carregado do PostgreSQL")
            return row[0]
    except Exception as e:
        print(f"PostgreSQL load erro: {e}")
    return None

def salvar_postgres(data):
    if not DATABASE_URL:
        return False
    try:
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL, sslmode="require")
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO bankroll (data) VALUES (%s) RETURNING id",
                (json.dumps(data),)
            )
            row = cur.fetchone()
        conn.commit()
        conn.close()
        print(f"PostgreSQL: salvo (id={row[0]})")
        return True
    except Exception as e:
        print(f"PostgreSQL save erro: {e}")
        return False

def salvar_local(data):
    with open("bankroll.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    print("bankroll.json: salvo localmente")

def main():
    print("=" * 60)
    print("CORREÇÃO BANKROLL v5.5 — 3 TRADES NO LIQUIDADOS ERRADO")
    print("=" * 60)

    data = carregar_postgres()
    if not data:
        try:
            with open("bankroll.json") as f:
                data = json.load(f)
            print("Carregado do bankroll.json local")
        except Exception as e:
            print(f"ERRO ao carregar: {e}")
            sys.exit(1)

    saldo_antes = float(data.get("balance", 0))
    print(f"\nSaldo antes:  ${saldo_antes:.4f}")
    print(f"Trades:       {len(data.get('history', []))}")

    print("\nAplicando correções...")
    data, n = aplicar_correcoes(data)

    if n == 0:
        print("\nNenhuma correção aplicada (já corrigido ou trades não encontrados).")
        return

    saldo_depois = float(data.get("balance", 0))
    print(f"\n{'='*60}")
    print(f"Saldo antes:  ${saldo_antes:.4f}")
    print(f"Saldo depois: ${saldo_depois:.4f}")
    print(f"Diferença:    ${saldo_depois - saldo_antes:+.4f}")
    print(f"Correções:    {n}/3")

    salvar_local(data)
    ok_pg = salvar_postgres(data)

    if not ok_pg:
        print("\nATENÇÃO: PostgreSQL falhou — rode este script no Railway.")
    print("=" * 60)

if __name__ == "__main__":
    main()
