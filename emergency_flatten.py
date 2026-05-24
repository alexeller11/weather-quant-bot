"""
Emergency utility to remove paper exposure after a model/risk reset.

It voids every OPEN trade with pnl=0 and recalculates balance from closed
trades only.  This does not execute real orders on Polymarket.
"""

import json
from datetime import datetime, timezone
from pathlib import Path


BANKROLL_FILE = Path("bankroll.json")


def utcnow_iso():
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def flatten_open_trades(reason="model recalibration emergency flatten"):
    data = json.loads(BANKROLL_FILE.read_text(encoding="utf-8"))
    history = data.get("history", [])
    closed_pnl = sum(
        float(t.get("pnl") or 0)
        for t in history
        if t.get("result") in ("WIN", "LOSS")
    )

    flattened = 0
    exposure_removed = 0.0
    now = utcnow_iso()

    for trade in history:
        if trade.get("result") != "OPEN":
            continue

        flattened += 1
        exposure_removed += float(trade.get("stake") or 0)
        trade["result"] = "VOID"
        trade["pnl"] = 0
        trade["exit_time"] = now
        trade["void_reason"] = reason

    start_balance = float(data.get("start_balance", data.get("balance", 0)))
    data["balance"] = round(start_balance + closed_pnl, 4)
    data["emergency_flattened_at"] = now
    data["emergency_flattened_trades"] = flattened
    data["emergency_flattened_exposure"] = round(exposure_removed, 2)

    BANKROLL_FILE.write_text(
        json.dumps(data, indent=4, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return {
        "flattened": flattened,
        "exposure_removed": round(exposure_removed, 2),
        "balance": data["balance"],
    }


if __name__ == "__main__":
    result = flatten_open_trades()
    print(
        "Flattened {flattened} OPEN trades, removed ${exposure_removed:.2f} "
        "paper exposure, balance=${balance:.2f}".format(**result)
    )
