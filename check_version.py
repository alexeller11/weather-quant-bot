"""
check_version.py — Diagnóstico rápido dos guardrails críticos.
Execute no Railway via: python check_version.py

Verifica:
  1. Se build_sigma() bloqueia sigma acima do cap
  2. Se build_sigma() PASSA sigma dentro do cap (teste positivo)
  3. Se TRADING_ENABLED está desligado
  4. Exposição atual vs limites
  5. Consistência de config.py vs CHANGELOG (exposição $8/4 trades)
"""

import json
from pathlib import Path

print("=" * 55)
print("WEATHER QUANT — DIAGNÓSTICO DE VERSÃO")
print("=" * 55)

# ── 1. Teste do fix crítico de model.py ──────────────────

print("\n[1] Testando build_sigma() ...")
try:
    from model import build_sigma
    from config import SIGMA_MAX_ABOVE_BELOW

    # Deve retornar None (sigma 8.0 > cap)
    resultado_alto = build_sigma(
        city_slug="denver",
        forecast_day=2,
        raw_sigma=8.0,
        condition="ABOVE",
    )

    if resultado_alto is None:
        print(f"    OK  build_sigma(sigma=8.0, ABOVE) retornou None — bloqueio ativo")
        print(f"    cap configurado: SIGMA_MAX_ABOVE_BELOW = {SIGMA_MAX_ABOVE_BELOW}")
    else:
        print(f"    PROBLEMA  build_sigma(sigma=8.0, ABOVE) retornou {resultado_alto}")
        print(f"    ACAO NECESSARIA: substituir model.py pela versão corrigida")

    # CORRIGIDO: também testa que sigma DENTRO do cap passa normalmente
    resultado_normal = build_sigma(
        city_slug="denver",
        forecast_day=2,
        raw_sigma=3.2,
        condition="ABOVE",
    )

    if resultado_normal is not None:
        print(f"    OK  build_sigma(sigma=3.2, ABOVE) retornou {resultado_normal:.4f} — trade permitido")
    else:
        print(f"    PROBLEMA  build_sigma(sigma=3.2) retornou None — cap muito apertado?")
        print(f"    Verificar SIGMA_MAX_ABOVE_BELOW = {SIGMA_MAX_ABOVE_BELOW}")

except Exception as e:
    print(f"    ERRO ao importar model.py: {e}")

# ── 2. TRADING_ENABLED ───────────────────────────────────

print("\n[2] Verificando TRADING_ENABLED ...")
try:
    from config import TRADING_ENABLED
    status = "LIGADO" if TRADING_ENABLED else "DESLIGADO (modo observação)"
    print(f"    TRADING_ENABLED = {TRADING_ENABLED} — {status}")
    if TRADING_ENABLED:
        print("    ACAO NECESSARIA: definir TRADING_ENABLED=0 nas variáveis do Railway")
except Exception as e:
    print(f"    ERRO: {e}")

# ── 3. Consistência config vs CHANGELOG ──────────────────

print("\n[3] Verificando consistência de limites de risco ...")
try:
    from config import MAX_TOTAL_EXPOSURE, MAX_OPEN_TRADES

    # CHANGELOG documenta: $8 e 4 abertos após emergency reset
    if MAX_TOTAL_EXPOSURE == 8.0 and MAX_OPEN_TRADES == 4:
        print(f"    OK  MAX_TOTAL_EXPOSURE=${MAX_TOTAL_EXPOSURE} MAX_OPEN_TRADES={MAX_OPEN_TRADES}")
        print(f"    Alinhado com CHANGELOG (emergency reset)")
    else:
        print(f"    DIVERGENCIA  MAX_TOTAL_EXPOSURE=${MAX_TOTAL_EXPOSURE} MAX_OPEN_TRADES={MAX_OPEN_TRADES}")
        print(f"    CHANGELOG documenta: $8 e 4 abertos")
        print(f"    ACAO NECESSARIA: verificar qual é o valor real em produção")
except Exception as e:
    print(f"    ERRO: {e}")

# ── 4. Exposição atual ───────────────────────────────────

print("\n[4] Lendo bankroll.json ...")
bf = Path("bankroll.json")
if not bf.exists():
    print("    bankroll.json não encontrado")
else:
    try:
        data = json.loads(bf.read_text(encoding="utf-8"))
        history = data.get("history", [])
        balance = float(data.get("balance", 0))

        open_trades = [t for t in history if t.get("result") == "OPEN"]
        exposure = sum(float(t.get("stake", 0)) for t in open_trades)

        from config import MAX_TOTAL_EXPOSURE, MAX_OPEN_TRADES, MAX_POSITION, SIGMA_MAX_ABOVE_BELOW

        print(f"    Saldo:          ${balance:.2f}")
        print(f"    Trades OPEN:    {len(open_trades)} / max {MAX_OPEN_TRADES}  {'OK' if len(open_trades) <= MAX_OPEN_TRADES else 'ACIMA DO LIMITE'}")
        print(f"    Exposição:      ${exposure:.2f} / max ${MAX_TOTAL_EXPOSURE:.2f}  {'OK' if exposure <= MAX_TOTAL_EXPOSURE else 'ACIMA DO LIMITE'}")

        sigma_bloqueados = [
            t for t in open_trades
            if t.get("sigma_total") and float(t.get("sigma_total", 0)) > SIGMA_MAX_ABOVE_BELOW
        ]

        if sigma_bloqueados:
            print(f"\n    Trades OPEN com sigma > {SIGMA_MAX_ABOVE_BELOW} (legado, pré-fix):")
            for t in sigma_bloqueados:
                print(
                    f"      {t.get('city'):15} {t.get('market_date')} "
                    f"sigma={t.get('sigma_total')} stake=${t.get('stake', 0):.2f}"
                )
        else:
            print(f"    Nenhum trade OPEN com sigma acima do cap — OK")

        stakes_altos = [
            t for t in open_trades
            if float(t.get("stake", 0)) > MAX_POSITION
        ]
        if stakes_altos:
            print(f"\n    Trades OPEN com stake > ${MAX_POSITION}:")
            for t in stakes_altos:
                print(
                    f"      {t.get('city'):15} {t.get('market_date')} "
                    f"stake=${t.get('stake', 0):.2f}"
                )

    except Exception as e:
        print(f"    ERRO ao ler bankroll: {e}")

# ── 5. validacao.json ────────────────────────────────────

print("\n[5] Verificando validacao.json ...")
vf = Path("validacao.json")
if not vf.exists():
    print("    Arquivo não encontrado — será criado pelo bot")
else:
    try:
        content = vf.read_text(encoding="utf-8").strip()
        if content.startswith("{") or content.startswith("["):
            json.loads(content)
            print("    OK  validacao.json é JSON válido")
        else:
            print("    PROBLEMA  validacao.json contém código Python (não JSON)")
    except json.JSONDecodeError:
        print("    PROBLEMA  validacao.json inválido")

# ── 6. Filtros ativos ────────────────────────────────────

print("\n[6] Filtros de entrada ativos ...")
try:
    from config import MIN_PROB_ABOVE_BELOW, MIN_TARGET_ZSCORE, MIN_EV
    print(f"    MIN_PROB_ABOVE_BELOW = {MIN_PROB_ABOVE_BELOW}  (recomendado: 0.70)")
    print(f"    MIN_TARGET_ZSCORE    = {MIN_TARGET_ZSCORE}   (recomendado: 1.50)")
    print(f"    MIN_EV               = {MIN_EV}  (mínimo razoável)")

    avisos = []
    if MIN_PROB_ABOVE_BELOW < 0.70:
        avisos.append(f"MIN_PROB_ABOVE_BELOW={MIN_PROB_ABOVE_BELOW} < 0.70 — aumentar para reduzir trades de baixa convicção")
    if MIN_TARGET_ZSCORE < 1.20:
        avisos.append(f"MIN_TARGET_ZSCORE={MIN_TARGET_ZSCORE} < 1.20 — aumentar para evitar zona de ruído")

    for aviso in avisos:
        print(f"    AVISO: {aviso}")

    if not avisos:
        print("    OK  Filtros conservadores ativos")
except Exception as e:
    print(f"    ERRO: {e}")

print("\n" + "=" * 55)
print("FIM DO DIAGNÓSTICO")
print("=" * 55 + "\n")
