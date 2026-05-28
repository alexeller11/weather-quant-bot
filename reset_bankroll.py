"""
reset_bankroll.py — Reseta o bankroll para um saldo inicial limpo.

CORRIGIDO: padrão era $1000, mas config.py define START_BALANCE=100.
Padrão agora lê de config.py para manter consistência.

USO:
    python reset_bankroll.py          # Reseta para START_BALANCE de config.py
    python reset_bankroll.py 500      # Reseta para $500

ATENÇÃO: apaga TODO o histórico de trades. Faça backup antes.
"""

import sys
import json
import shutil
import os
from datetime import datetime

BANKROLL_FILE = "bankroll.json"


def backup_bankroll():
    if os.path.exists(BANKROLL_FILE):
        ts     = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup = f"bankroll_backup_{ts}.json"
        shutil.copy2(BANKROLL_FILE, backup)
        print(f"Backup salvo em: {backup}")
        return backup
    return None


def reset(starting_balance=None):
    # CORRIGIDO: lê padrão de config.py em vez de hardcodar $1000
    if starting_balance is None:
        try:
            from config import START_BALANCE
            starting_balance = START_BALANCE
        except Exception:
            starting_balance = 100.0

    backup = backup_bankroll()

    data = {
        "balance":       starting_balance,
        "start_balance": starting_balance,
        "history":       [],
        "reset_at":      datetime.utcnow().isoformat(),
        "backup":        backup,
    }

    with open(BANKROLL_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

    print(f"\nBankroll resetado.")
    print(f"  Saldo inicial: ${starting_balance:.2f}")
    print(f"  Histórico: limpo")
    if backup:
        print(f"  Backup: {backup}")


if __name__ == "__main__":
    balance = float(sys.argv[1]) if len(sys.argv) > 1 else None

    try:
        from config import START_BALANCE
        default_balance = balance if balance is not None else START_BALANCE
    except Exception:
        default_balance = balance if balance is not None else 100.0

    confirm = input(
        f"\nISSO VAI APAGAR TODO O HISTÓRICO.\n"
        f"Resetar bankroll para ${default_balance:.2f}? [s/N] "
    ).strip().lower()

    if confirm == "s":
        reset(default_balance)
    else:
        print("Cancelado.")
