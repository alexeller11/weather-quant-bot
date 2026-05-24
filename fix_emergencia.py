from datetime import datetime
from bankroll import load_bankroll, save_bankroll

data = load_bankroll()
today = datetime.utcnow().date()
fechados = 0

for trade in data["history"]:
    if trade.get("result") != "OPEN":
        continue
    try:
        d = datetime.strptime(trade["market_date"], "%Y-%m-%d").date()
    except:
        continue
    if d < today:
        stake = float(trade.get("stake", 0))
        trade["result"] = "LOSS"
        trade["pnl"] = round(-stake, 2)
        trade["fee"] = 0.0
        trade["exit_time"] = datetime.utcnow().isoformat()
        print(f"Fechando: {trade.get('city')} {trade['market_date']} ${stake:.2f}")
        fechados += 1

print(f"Total fechados: {fechados}")
save_bankroll(data)
print("Salvo!")
