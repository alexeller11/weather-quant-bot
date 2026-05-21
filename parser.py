
import re

def normalize_market(question):
    q = question.lower()

    condition = "between"

    if "above" in q or "over" in q:
        condition = "above"
    elif "below" in q or "under" in q:
        condition = "below"

    temps = re.findall(r"(\d+(?:\.\d+)?)", q)

    if not temps:
        return None

    target = float(temps[-1])

    if "f" in q:
        target = (target - 32) * 5 / 9

    city_match = re.search(r"in ([a-zA-Z ]+)", q)

    city = city_match.group(1).strip() if city_match else "unknown"

    return {
        "city": city,
        "target_c": round(target, 2),
        "condition": condition
    }
