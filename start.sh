#!/usr/bin/env bash
# Inicia o loop do bot em segundo plano
python bot.py &

# Inicia o painel do dashboard em primeiro plano
python dashboard.py
