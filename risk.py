# =========================================================
# WEATHER QUANT BOT — RISK (CORRIGIDO)
# =========================================================

from config import (
    MAX_TOTAL_EXPOSURE,
    MAX_POSITION,
    KELLY_FRACTION,
)

# =========================================================
# KELLY
# =========================================================

def kelly_stake(

    bankroll,

    prob,

    market_price,
):
    """
    Calcula stake via Kelly Criterion com half-kelly e cap.
    
    FIX #8: Simplificado e explícito.
    """

    try:

        # Odds
        b = (
            (1.0 / market_price)
            - 1.0
        )

        p = float(prob)
        q = 1.0 - p

        # Kelly puro
        kelly_puro = (
            ((b * p) - q)
            / b
        )

        # Half Kelly
        kelly_half = kelly_puro * KELLY_FRACTION

        # Cap
        kelly_capped = min(
            kelly_half,
            MAX_POSITION
        )

        if kelly_capped <= 0:
            return 0

        stake = bankroll * kelly_capped

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
# STAKE CAP (SIMPLIFICADO)
# =========================================================

def cap_stake_by_type(
    stake,
    condition,
):
    """
    FIX #8: Cap removido — já é feito em kelly_stake.
    Essa função agora só reduz para EXACT (mais arriscado).
    """

    if condition.upper() == "EXACT":
        # EXACT é arriscado — reduz 40%
        stake *= 0.60
    # ABOVE/BELOW — sem redução adicional

    return round(
        max(stake, 0),
        2
    )
