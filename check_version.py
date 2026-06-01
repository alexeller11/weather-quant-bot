"""
check_version.py — Diagnóstico rápido v5.
Execute no Railway via: python check_version.py
"""

import json
from pathlib import Path

print("=" * 55)
print("WEATHER QUANT v5 — DIAGNÓSTICO")
print("=" * 55)

# ── 1. Testa calculate_probability com range2 ────────────
print("\n[1] Testando model.py v5 ...")
try:
    from model import calculate_probability
    # Testa range2: forecast=74°F≈23.3°C, bucket 72-73°F
    prob = calculate_probability(
        city="New York", target_temp=72.5, forecast_temp=23.3,
        day_offset=1, condition="RANGE2", unit="F",
        sigma=4.0, target_lo=72.0, target_hi=73.0,
    )
    if 0 < prob < 1:
        print(f"    OK  calculate_probability(RANGE2) = {prob:.4f}")
    else:
        print(f"    PROBLEMA  prob={prob} fora de [0,1]")

    prob2 = calculate_probability(
        city="London", target_temp=20.0, forecast_temp=23.0,
        day_offset=1, condition="ABOVE", unit="C", sigma=4.0,
    )
    print(f"    OK  calculate_probability(ABOVE) = {prob2:.4f}")
except Exception as e:
    print(f"    ERRO: {e}")

# ── 2. Testa gamma_parser parse_question ─────────────────
print("\n[2] Testando gamma_parser.py v5 ...")
try:
    from gamma_parser import parse_question
    casos = [
        ("50°F or higher",  "above",  50.0, "F"),
        ("31°F or below",   "below",  31.0, "F"),
        ("48-49°F",         "range2", 48.5, "F"),
        ("13°C or higher",  "above",  13.0, "C"),
        ("24°C",            "exact",  24.0, "C"),
    ]
    ok = 0
    for question, exp_cond, exp_target, exp_unit in casos:
        r = parse_question(question)
        if r and r["condition"] == exp_cond and abs(r["target"] - exp_target) < 0.1:
            ok += 1
        else:
            print(f"    FALHOU: '{question}' → {r}")
    print(f"    OK  {ok}/{len(casos)} casos reconhecidos corretamente")
except Exception as e:
    print(f"    ERRO: {e}")

# ── 3. TRADING_ENABLED ───────────────────────────────────
print("\n[3] Verificando TRADING_ENABLED ...")
try:
    from config import TRADING_ENABLED, MIN_PRICE, MAX_POSITION, MAX_TOTAL_EXPOSURE
    status = "LIGADO ⚠" if TRADING_ENABLED else "DESLIGADO (observação)"
    print(f"    TRADING_ENABLED = {TRADING_ENABLED} — {status}")
    print(f"    MIN_PRICE       = {MIN_PRICE}  (esperado: 0.10)")
    print(f"    MAX_POSITION    = ${MAX_POSITION}  (esperado: $4.00)")
    print(f"    MAX_EXPOSURE    = ${MAX_TOTAL_EXPOSURE}  (esperado: $20.00)")
    if MIN_PRICE != 0.10:
        print(f"    AVISO: MIN_PRICE={MIN_PRICE} — esperado 0.10")
except Exception as e:
    print(f"    ERRO: {e}")

# ── 4. Bankroll ──────────────────────────────────────────
print("\n[4] Lendo bankroll.json ...")
bf = Path("bankroll.json")
if not bf.exists():
    print("    bankroll.json não encontrado (normal se só usa PostgreSQL)")
else:
    try:
        data     = json.loads(bf.read_text(encoding="utf-8"))
        history  = data.get("history", [])
        balance  = float(data.get("balance", 0))
        abertos  = [t for t in history if t.get("result") == "OPEN"]
        fechados = [t for t in history if t.get("result") in ("WIN","LOSS")]
        exposure = sum(float(t.get("stake", 0)) for t in abertos)
        print(f"    Saldo:    ${balance:.2f}")
        print(f"    Abertos:  {len(abertos)}  (exposição ${exposure:.2f})")
        print(f"    Fechados: {len(fechados)}")

        # Verifica se há trades com tipo range2
        range2 = [t for t in history if t.get("type","").upper() == "RANGE2"]
        if range2:
            print(f"    Trades RANGE2: {len(range2)}")
    except Exception as e:
        print(f"    ERRO: {e}")

# ── 5. Variáveis de ambiente ─────────────────────────────
print("\n[5] Variáveis de ambiente ...")
import os
vars_check = [
    ("TELEGRAM_TOKEN", True),
    ("CHAT_ID",        True),
    ("DATABASE_URL",   True),
    ("GROQ_API_KEY",   False),
    ("GITHUB_TOKEN",   False),
    ("WEATHERAPI_KEY", False),
]
for var, required in vars_check:
    val = os.getenv(var, "")
    if val:
        print(f"    OK  {var} configurado")
    elif required:
        print(f"    AVISO  {var} não configurado (necessário)")
    else:
        print(f"    INFO   {var} não configurado (opcional)")

print("\n" + "=" * 55)
print("FIM DO DIAGNÓSTICO v5")
print("=" * 55)
