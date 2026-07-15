import json

with open("bankroll.json", "r", encoding="utf-8") as f:
    data = json.load(f)

history = data.get("history", [])
open_trades = [t for t in history if t.get("result") == "OPEN"]
print(f"Total open trades: {len(open_trades)}")
for t in open_trades:
    print(f"  City: {t.get('city')}, Market Date: {t.get('market_date')}, Type: {t.get('type')}, Side: {t.get('side')}, Stake: {t.get('stake')}, ID: {t.get('market_id')}")
