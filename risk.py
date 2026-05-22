# =========================================================
# WEATHER QUANT BOT — RISK
# =========================================================

from config import (
    MAX_POSITION,
    KELLY_FRACTION,
    MAX_TOTAL_EXPOSURE,
    MAX_POSITION_DOLARES,
    EXACT_STAKE_MULTIPLIER,
)

# =========================================================
# KELLY
# =========================================================

def kelly_stake(current_balance: float,
                 model_prob: float,
                 market_price: float) -> float:

    if market_price <= 0 or market_price >= 1:
        return 0.0

    if current_balance <= 0:
        return 0.0

    p = float(model_prob)
    q = 1.0 - p

    b = (1.0 / float(market_price)) - 1.0

    if b <= 0:
        return 0.0

    f_star = (p * b - q) / b

    if f_star <= 0:
        return 0.0

    fraction = min(
        f_star * KELLY_FRACTION,
        MAX_POSITION
    )

    stake = current_balance * fraction

    return round(max(stake, 0.0), 2)

# =========================================================
# EV
# =========================================================

def expected_value(model_prob: float,
                   market_price: float) -> float:

    if market_price <= 0:
        return 0.0

    ev = (float(model_prob) / float(market_price)) - 1.0

    return round(ev, 4)

# =========================================================
# EXPOSIÇÃO
# =========================================================

def open_exposure(history: list) -> float:

    total = 0.0

    for trade in history:
        if trade.get("result") == "OPEN":
            total += float(trade.get("stake", 0.0))

    return round(total, 2)

# =========================================================
# CAPACIDADE
# =========================================================

def remaining_capacity(history: list) -> float:

    exposure = open_exposure(history)

    remaining = MAX_TOTAL_EXPOSURE - exposure

    return round(max(remaining, 0.0), 2)

# =========================================================
# CAP DE STAKE
# =========================================================

def cap_stake_by_type(stake: float,
                      trade_type: str) -> float:

    stake = min(
        float(stake),
        float(MAX_POSITION_DOLARES)
    )

    if str(trade_type).upper() == "EXACT":
        exact_cap = (
            float(MAX_POSITION_DOLARES)
            * float(EXACT_STAKE_MULTIPLIER)
        )

        stake = min(stake, exact_cap)

    return round(max(stake, 0.0), 2)
