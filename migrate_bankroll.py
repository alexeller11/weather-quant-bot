"""
migrate_bankroll.py — Importa bankroll.json local para o PostgreSQL.

Execute UMA VEZ após configurar DATABASE_URL no Railway.

CORRIGIDO: a versão anterior tinha um bankroll inteiro hardcoded com saldo
desatualizado ($21.16 de um snapshot antigo). Rodar o script acidentalmente
sobrescrevia o bankroll real no PostgreSQL. Agora o script lê o bankroll.json
local (a fonte de verdade atual) e o importa para o banco.

Uso:
    DATABASE_URL=postgres://... python migrate_bankroll.py
"""

import os
import json
import sys

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    print("DATABASE_URL não configurada.")
    sys.exit(1)

BANKROLL_FILE = "bankroll.json"

if not os.path.exists(BANKROLL_FILE):
    print(f"Arquivo '{BANKROLL_FILE}' não encontrado.")
    print("Execute este script no mesmo diretório que contém o bankroll.json.")
    sys.exit(1)

try:
    with open(BANKROLL_FILE, "r", encoding="utf-8") as f:
        bankroll = json.load(f)
except Exception as e:
    print(f"Erro ao ler {BANKROLL_FILE}: {e}")
    sys.exit(1)

print(f"Bankroll local:")
print(f"  Saldo:  ${bankroll.get('balance', 0):.2f}")
print(f"  Trades: {len(bankroll.get('history', []))} "
      f"({sum(1 for t in bankroll.get('history', []) if t.get('result')=='OPEN')} abertos)")

confirm = input("\nImportar este bankroll para o PostgreSQL? [s/N] ").strip().lower()
if confirm != "s":
    print("Cancelado.")
    sys.exit(0)

try:
    import psycopg2
    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bankroll (
                id       SERIAL PRIMARY KEY,
                data     JSONB NOT NULL,
                saved_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("SELECT COUNT(*) FROM bankroll")
        count = cur.fetchone()[0]
        if count > 0:
            print(f"\nBanco já tem {count} registro(s).")
            resp = input("Sobrescrever? [s/N] ").strip().lower()
            if resp != "s":
                print("Cancelado.")
                conn.close()
                sys.exit(0)
            cur.execute("DELETE FROM bankroll")
            print("Registros anteriores removidos.")

        cur.execute(
            "INSERT INTO bankroll (data) VALUES (%s)",
            (json.dumps(bankroll),)
        )
    conn.commit()
    conn.close()
    print(f"\nBankroll importado com sucesso!")
    print(f"  Saldo: ${bankroll['balance']:.2f}")
    print(f"  Trades: {len(bankroll.get('history', []))}")
except Exception as e:
    print(f"Erro: {e}")
    sys.exit(1)
