#!/usr/bin/env python3
"""
fix_db.py — Injeta bankroll.json corrigido no PostgreSQL.
Rode no Railway: python fix_db.py
"""
import os, json, psycopg2

conn = psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")
with open("bankroll.json") as f:
    data = json.load(f)
with conn.cursor() as cur:
    cur.execute("INSERT INTO bankroll (data) VALUES (%s)", (json.dumps(data),))
conn.commit()
conn.close()
print(f"OK! Saldo: ${data['balance']:.2f} | Trades: {len(data['history'])}")
