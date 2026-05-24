# =========================================================
# WEATHER QUANT BOT — MODEL (CORRIGIDO)
# =========================================================

from statistics import NormalDist
import math

from config import (

    SIGMA_ENSEMBLE_INFLATION,

    CITY_SIGMA_CLIMO,

    SIGMA_MIN_EXACT,

    CITY_MIN_SIGMA,

    SIGMA_MAX_ABOVE_BELOW,

    SIGMA_MAX_EXACT,
)

# =========================================================
# TEMP
# =========================================================

def to_celsius(
    temp,
    unit="C"
):

    if unit.upper() == "F":

        return (
            (float(temp) - 32.0)
            * 5.0
            / 9.0
        )

    return float(temp)

# =========================================================
# SIGMA
# =========================================================

def build_sigma(

    city_slug,

    forecast_day,

    raw_sigma,

    condition="",
):

    sigma_used = max(float(raw_sigma), 0.10)

    inflation = (
        SIGMA_ENSEMBLE_INFLATION.get(
            forecast_day,
            2.0
        )
    )

    sigma_ens = sigma_used * inflation

    sigma_clim = (
        CITY_SIGMA_CLIMO.get(
            city_slug,
            2.0
        )
    )

    # raw_sigma already represents forecast uncertainty.  The city value is a
    # floor, not another independent error term; summing both in quadrature was
    # double counting uncertainty and creating false 40-55% probabilities.
    sigma_total = max(sigma_ens, sigma_clim)

    # =====================================================
    # EXACT — FIX #9: REJEITAR SE MUITO BAIXO
    # =====================================================

    condition_upper = condition.upper()

    if condition_upper == "EXACT":

        if sigma_total < SIGMA_MIN_EXACT:

            print(
                f"  ⚠️  EXACT com sigma "
                f"muito baixa "
                f"({sigma_total:.2f} < "
                f"{SIGMA_MIN_EXACT:.2f}) "
                f"— pode dar prob irrealista"
            )

            # Em vez de forçar, retorna None para rejeitar
            return None

    # =====================================================
    # CITY MIN
    # =====================================================

    city_min = CITY_MIN_SIGMA.get(city_slug)

    if city_min and sigma_total < city_min:
        sigma_total = city_min

    sigma_cap = (
        SIGMA_MAX_EXACT
        if condition_upper == "EXACT"
        else SIGMA_MAX_ABOVE_BELOW
    )

    if sigma_total > sigma_cap:
        print(
            f"  Sigma alto demais "
            f"({sigma_total:.2f} > {sigma_cap:.2f}) — skip"
        )
        return None

    return round(
        sigma_total,
        4
    )

# =========================================================
# PROBABILITY
# =========================================================

def calculate_probability(

    forecast_c,

    sigma,

    target,

    condition,

    unit="C"
):

    # Checar se sigma é None (FIX #9)
    if sigma is None:
        return 0.0

    target_c = to_celsius(
        target,
        unit
    )

    dist = NormalDist(

        mu=float(forecast_c),

        sigma=max(
            float(sigma),
            0.10
        )
    )

    condition = condition.upper()

    # =====================================================
    # ABOVE
    # =====================================================

    if condition == "ABOVE":

        return round(
            1.0 - dist.cdf(target_c),
            4
        )

    # =====================================================
    # BELOW
    # =====================================================

    if condition == "BELOW":

        return round(
            dist.cdf(target_c),
            4
        )

    # =====================================================
    # EXACT
    # =====================================================

    if condition == "EXACT":

        if unit.upper() == "F":

            half_window_c = 0.2777777778

        else:

            half_window_c = 0.5

        lower = (
            target_c
            - half_window_c
        )

        upper = (
            target_c
            + half_window_c
        )

        prob = (
            dist.cdf(upper)
            - dist.cdf(lower)
        )

        return round(
            prob,
            4
        )

    return 0.0
