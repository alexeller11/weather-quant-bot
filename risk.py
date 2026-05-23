# =========================================================
# WEATHER QUANT BOT — RISK
# FIX: kelly_stake usa MAX_KELLY_FRACTION_CAP (0.20) como
#      cap de FRAÇÃO, não MAX_POSITION (10.0 = dólares).
#      Sem isso, Kelly nunca era capado como fração —
#      num bankroll de $100 apostaria $46 em Denver 56F.
# =========================================================

from config import (
    MAX_TOTAL_EXPOSURE,
    MAX_KELLY_FRACTION_CAP,
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
    Calcula stake via Kelly Criterion.

    Pipeline:
    1. Kelly puro  = (b*p - q) / b
    2. Half-Kelly  = kelly_puro * KELLY_FRACTION (0.5)
    3. Cap fração  = min(half_kelly, MAX_KELLY_FRACTION_CAP) (0.20)
    4. Stake $     = bankroll * cap_fração

    O cap em dólares (MAX_POSITION_DOLARES) é aplicado em bot.py
    depois de converter para shares.
    """

    try:

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

        # Half-Kelly
        kelly_half = (
            kelly_puro * KELLY_FRACTION
        )

        # Cap como FRAÇÃO do bankroll (ex: 0.20 = máx 20%)
        kelly_capped = min(
            kelly_half,
            MAX_KELLY_FRACTION_CAP
        )

        if kelly_capped <= 0:
            return 0

        stake = bankroll * kelly_capped

        return round(
            max(stake, 0),
            2
        )

    except Exception:
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

    except Exception:
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
# STAKE CAP POR TIPO
# =========================================================

def cap_stake_by_type(
    stake,
    condition,
):
    """
    Reduz stake para EXACT (mais arriscado que ABOVE/BELOW).
    O cap em dólares absolutos (MAX_POSITION_DOLARES) é feito em bot.py.
    """

    if condition.upper() == "EXACT":
        stake *= 0.60

    return round(
        max(stake, 0),
        2
    )
