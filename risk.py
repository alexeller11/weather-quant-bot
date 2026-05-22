# =========================================================
# WEATHER QUANT BOT — RISK
# =========================================================

from config import (
    MAX_TOTAL_EXPOSURE
)

# =========================================================
# KELLY
# =========================================================

def kelly_stake(

    bankroll,

    prob,

    market_price,
):

    try:

        b = (
            (1.0 / market_price)
            - 1.0
        )

        p = prob

        q = 1.0 - p

        kelly = (
            ((b * p) - q)
            / b
        )

        # =====================================
        # HALF KELLY
        # =====================================

        kelly *= 0.50

        if kelly <= 0:
            return 0

        stake = bankroll * kelly

        return round(
            max(stake, 0),
            2
        )

    except:
        return 0

# =========================================================
# EV
# =========================================================

def expected_value(
    prob,
    market_price
):

    try:

        payout = (
            1.0
            - market_price
        )

        loss = market_price

        ev = (
            (prob * payout)
            - ((1 - prob) * loss)
        )

        return round(ev, 4)

    except:
        return 0

# =========================================================
# EXPOSURE
# =========================================================

def open_exposure(history):

    total = 0

    for trade in history:

        if trade.get("result") == "OPEN":

            total += float(
                trade.get(
                    "stake",
                    0
                )
            )

    return round(total, 2)

# =========================================================
# REMAINING
# =========================================================

def remaining_capacity(history):

    exposure = open_exposure(
        history
    )

    return round(
        max(
            MAX_TOTAL_EXPOSURE
            - exposure,
            0
        ),
        2
    )

# =========================================================
# STAKE CAP
# =========================================================

def cap_stake_by_type(
    stake,
    condition
):

    if condition.upper() == "EXACT":

        stake *= 0.40

    else:

        stake *= 0.75

    return round(
        max(stake, 0),
        2
    )
