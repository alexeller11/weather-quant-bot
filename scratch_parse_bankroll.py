import json
from collections import Counter

with open("bankroll.json", "r", encoding="utf-8") as f:
    data = json.load(f)

history = data.get("history", [])
print(f"Total trades in history: {len(history)}")

recent_trades = [t for t in history if t.get("market_date", "") >= "2026-06-01"]
print(f"Recent trades (since 2026-06-01): {len(recent_trades)}")

city_counts = Counter(t.get("city") for t in recent_trades)
print("\nRecent trades by city:")
for city, count in city_counts.items():
    print(f"  {city}: {count}")

print("\nLast 10 trades:")
for t in history[-10:]:
    print(f"  {t.get('market_date')} - {t.get('city')} - {t.get('type')} - {t.get('side')} - {t.get('result')}")
