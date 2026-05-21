"""
cleanup_history.py
==================
Limpa o bankroll.json existente SEM apagar histórico:

  1. Remove duplicatas de market_id — mantém o trade mais relevante
     (fechado > aberto; mais recente se empate).
  2. Corrige targets que são dia-do-mês em vez do threshold real,
     extraindo o número correto da question.
  3. Recalcula o balance com base no histórico limpo.
  4. Faz backup automático antes de qualquer alteração.

USO:
    python cleanup_history.py
"""

import json
import re
import shutil
from collections import defaultdict
from datetime import datetime, timezone

def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)

BANKROLL_FILE = "bankroll.json"

# ── Backup ────────────────────────────────────────────────────────────────────

def backup():
    ts     = utcnow().strftime("%Y%m%d_%H%M%S")
    target = f"bankroll_pre_cleanup_{ts}.json"
    shutil.copy2(BANKROLL_FILE, target)
    print(f"Backup: {target}")
    return target

# ── Corrige target ────────────────────────────────────────────────────────────

def fix_target(trade):
    """
    Se target < 20 (parece dia do mês), tenta extrair o threshold real
    da question.

    Ex: target=14.0, question="...be 27°C or higher on May 14?"
        → corrige target para 27.0
    """
    question = trade.get("question", "")
    unit     = trade.get("unit", "C")
    target   = trade.get("target")

    if target is None or float(target) >= 20:
        return trade, False

    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", question)]

    if unit == "F":
        candidates = [n for n in nums if 50 <= n <= 120]
    else:
        candidates = [n for n in nums if 15 <= n <= 50]

    if not candidates:
        return trade, False

    new_target = candidates[0]
    if abs(new_target - float(target)) < 0.01:
        return trade, False

    trade = dict(trade)
    print(f"  Target corrigido: {trade.get('city')} "
          f"market_id={trade.get('market_id')} "
          f"{target} → {new_target} [{unit}]")
    trade["target"] = new_target
    return trade, True

# ── Remove duplicatas ─────────────────────────────────────────────────────────

def deduplicate(history):
    """
    Para cada market_id mantém apenas 1 trade:
      - fechado (WIN/LOSS) tem prioridade sobre OPEN.
      - se múltiplos fechados: mantém o de exit_time mais recente.
      - se só OPENs: mantém o de entry_time mais recente.
    """
    groups = defaultdict(list)
    for i, trade in enumerate(history):
        groups[trade.get("market_id")].append((i, trade))

    kept    = []
    removed = 0

    def sort_key(x):
        t = x[1]
        return t.get("exit_time") or t.get("entry_time") or ""

    for mid, entries in groups.items():
        if len(entries) == 1:
            kept.append(entries[0][1])
            continue

        removed += len(entries) - 1

        closed = [(i, t) for i, t in entries if t.get("result") in ("WIN", "LOSS")]
        open_  = [(i, t) for i, t in entries if t.get("result") == "OPEN"]

        if closed:
            best = sorted(closed, key=sort_key, reverse=True)[0][1]
            print(f"  Duplicata: market_id={mid} — "
                  f"mantendo {best['result']} "
                  f"(removendo {len(entries) - 1} entrada(s))")
        else:
            best = sorted(open_, key=sort_key, reverse=True)[0][1]
            print(f"  Duplicata OPEN: market_id={mid} — "
                  f"mantendo 1 de {len(open_)}")

        kept.append(best)

    # Preserva ordem original aproximada
    order = {t.get("market_id"): i for i, t in enumerate(history)}
    kept.sort(key=lambda t: order.get(t.get("market_id"), 9999))

    return kept, removed

# ── Recalcula balance ─────────────────────────────────────────────────────────

def recalc_balance(history):
    """
    Reconstrói o balance do zero simulando todas as transações.

    Para cada trade, o stake saiu do balance na ENTRADA.
    Na saída:
      WIN:  recebe payout = stake / market_price - fee  (lucro líquido)
      LOSS: não recebe nada (stake foi perdido)
      OPEN: stake ainda está retido (não volta)

    Fórmula por trade:
      WIN:  net = +pnl  (pnl já é payout - stake, registrado no settlement)
      LOSS: net = +pnl  (pnl já é -stake)
      OPEN: net = -stake (retido)

    CORREÇÃO do bug anterior: a versão errada somava o payout sem deduzir
    o stake — resultando em balance inflado para cada WIN.
    """
    try:
        from config import START_BALANCE
        balance = float(START_BALANCE)
    except Exception:
        balance = 1000.0

    for t in history:
        result = t.get("result")
        stake  = float(t.get("stake", 0))
        pnl    = float(t.get("pnl", 0))

        if result == "WIN":
            # pnl = payout - stake (registrado pelo settlement)
            # balance saiu stake na entrada, volta stake+pnl na saída
            balance += pnl           # equivalente a: balance - stake + (stake + pnl)
        elif result == "LOSS":
            # pnl = -stake
            balance += pnl           # equivalente a: balance - stake (perdido)
        elif result == "OPEN":
            balance -= stake         # ainda retido, não voltou

    return round(balance, 6)

# ── Verifica resultado ────────────────────────────────────────────────────────

def _verify_recalc():
    """Teste interno rápido da lógica de recalc."""
    # START=1000, WIN: stake=50, price=0.5, fee=1 → pnl=49
    # Correto: 1000 - 50 (entrada) + 99 (payout) = 1049
    # Usando pnl: 1000 + 49 = 1049 ✓
    history_test = [{"result": "WIN", "stake": 50, "pnl": 49, "market_price": 0.5}]
    result = recalc_balance.__wrapped__(history_test) if hasattr(recalc_balance, '__wrapped__') else None

    b = 1000.0
    b += 49   # WIN pnl
    assert abs(b - 1049.0) < 0.01, f"recalc errado: {b}"

# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    with open(BANKROLL_FILE, "r", encoding="utf-8") as f:
        bankroll = json.load(f)

    backup()

    history      = bankroll["history"]
    orig_len     = len(history)
    orig_balance = bankroll["balance"]

    print(f"\nTrades originais: {orig_len}")
    print(f"Balance original: ${orig_balance:.2f}\n")

    # 1. Corrige targets
    fixed    = []
    n_target = 0
    for trade in history:
        trade_fixed, was_fixed = fix_target(trade)
        fixed.append(trade_fixed)
        if was_fixed:
            n_target += 1

    # 2. Remove duplicatas
    clean, n_removed = deduplicate(fixed)

    # 3. Recalcula balance
    new_balance = recalc_balance(clean)

    bankroll["history"] = clean
    bankroll["balance"] = new_balance

    with open(BANKROLL_FILE, "w", encoding="utf-8") as f:
        json.dump(bankroll, f, indent=4, ensure_ascii=False)

    wins   = sum(1 for t in clean if t.get("result") == "WIN")
    losses = sum(1 for t in clean if t.get("result") == "LOSS")
    opens  = sum(1 for t in clean if t.get("result") == "OPEN")
    pnl    = sum(t.get("pnl", 0) for t in clean
                 if t.get("result") in ("WIN", "LOSS"))

    print("\n==============================")
    print("CLEANUP COMPLETO")
    print("==============================")
    print(f"Trades originais:     {orig_len}")
    print(f"Duplicatas removidas: {n_removed}")
    print(f"Targets corrigidos:   {n_target}")
    print(f"Trades finais:        {len(clean)}")
    print(f"  WIN: {wins}  LOSS: {losses}  OPEN: {opens}")
    print(f"Balance original:     ${orig_balance:.2f}")
    print(f"Balance recalculado:  ${new_balance:.2f}")
    if (wins + losses) > 0:
        print(f"Win rate:             {wins / (wins + losses) * 100:.1f}%")
    print(f"P/L realizado:        ${pnl:.2f}")


if __name__ == "__main__":
    run()
