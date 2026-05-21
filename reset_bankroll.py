"""
reset_bankroll.py
=================
Reseta o bankroll para um saldo inicial limpo.

USO:
    python reset_bankroll.py             # Reseta para $1000 (START_BALANCE)
    python reset_bankroll.py 500         # Reseta para $500

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
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup = f"bankroll_backup_{ts}.json"
        shutil.copy2(BANKROLL_FILE, backup)
        print(f"Backup salvo em: {backup}")
        return backup
    return None

def reset(starting_balance=1000.0):
    backup = backup_bankroll()

    data = {
        "balance": starting_balance,
        "history": [],
        "reset_at": datetime.utcnow().isoformat(),
        "backup":   backup,
    }

    with open(BANKROLL_FILE, "w") as f:
        json.dump(data, f, indent=4)

    print(f"\nBankroll resetado.")
    print(f"  Saldo inicial: ${starting_balance:.2f}")
    print(f"  Histórico: limpo")
    if backup:
        print(f"  Backup: {backup}")


if __name__ == "__main__":
    balance = float(sys.argv[1]) if len(sys.argv) > 1 else 1000.0

    confirm = input(
        f"\nISSO VAI APAGAR TODO O HISTÓRICO.\n"
        f"Resetar bankroll para ${balance:.2f}? [s/N] "
    ).strip().lower()

    if confirm == "s":
        reset(balance)
    else:
        print("Cancelado.")
