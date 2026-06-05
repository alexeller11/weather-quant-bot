#!/usr/bin/env python3
"""
fix_db.py — Força atualização do bankroll no PostgreSQL.
Funciona porque o próprio bankroll.py já tem psycopg2 instalado
como dependência do projeto (requirements.txt).
"""
import os, sys

# Adiciona o diretório do app ao path
sys.path.insert(0, "/app")

# Importa as funções do próprio projeto
from bankroll import save_bankroll
import json

with open("bankroll.json") as f:
    data = json.load(f)

print(f"Carregado: saldo=${data['balance']:.2f}, trades={len(data['history'])}")
save_bankroll(data)
print("Salvo no PostgreSQL via bankroll.py!")
