import requests
import json
from datetime import datetime, timedelta

BASE_URL = "https://gamma-api.polymarket.com"

cities = ["new-york", "london", "tokyo", "los-angeles", "sao-paulo"]
today = datetime.utcnow().date()

for city in cities:
    print(f"\n=== CITY: {city} ===")
    for i in range(0, 2):
        d = today + timedelta(days=i)
        month = d.strftime('%B').lower()
        day = d.day
        year = d.year
        slug = f"highest-temperature-in-{city}-on-{month}-{day}"
        slug_year = f"highest-temperature-in-{city}-on-{month}-{day}-{year}"
        
        for s in [slug, slug_year]:
            url = f"{BASE_URL}/events?slug={s}"
            try:
                r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
                data = r.json()
                if data and isinstance(data, list) and len(data) > 0:
                    print(f"FOUND: slug={s} -> title: {data[0].get('title')} | markets count: {len(data[0].get('markets', []))}")
                else:
                    # print(f"NOT FOUND: slug={s}")
                    pass
            except Exception as e:
                print(f"Error for slug {s}: {e}")
