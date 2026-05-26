"""
cleanup_history.py — Utilitário para corrigir targets errados no bankroll.

CORRIGIDO: adicionado `import re` que estava faltando,
tornando o arquivo inutilizável isoladamente.

Uso:
    python cleanup_history.py
"""

import re
import json
from pathlib import Path

BANKROLL_FILE = Path("bankroll.json")


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

    # Preferir padrão "be <número><unidade>"
    match = re.search(
        r"be\s+(\d+(?:\.\d+)?)\s*°[CcFf]",
        question,
        re.IGNORECASE
    )

    if match:
        new_target = float(match.group(1))
        if unit == "C" and new_target > 55:
            unit = "F"
        if abs(new_target - float(target)) > 0.01:
            trade = dict(trade)
            print(f"  Target corrigido: {trade.get('city')} "
                  f"market_id={trade.get('market_id')} "
                  f"{target} → {new_target} [{unit}]")
            trade["target"] = new_target
            trade["unit"]   = unit
            return trade, True
        return trade, False

    # Fallback: extração por range (menos confiável)
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


def run_cleanup():
    """Aplica fix_target a todos os trades do bankroll."""
    if not BANKROLL_FILE.exists():
        print("bankroll.json não encontrado.")
        return

    data    = json.loads(BANKROLL_FILE.read_text(encoding="utf-8"))
    history = data.get("history", [])

    corrigidos = 0
    new_history = []
    for trade in history:
        fixed_trade, changed = fix_target(trade)
        new_history.append(fixed_trade)
        if changed:
            corrigidos += 1

    data["history"] = new_history

    BANKROLL_FILE.write_text(
        json.dumps(data, indent=4, ensure_ascii=False) + "\n",
        encoding="utf-8"
    )

    print(f"\nConcluído. Trades corrigidos: {corrigidos}")


if __name__ == "__main__":
    run_cleanup()
