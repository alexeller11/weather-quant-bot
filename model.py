# =========================================================
# WEATHER QUANT BOT — MODEL
# =========================================================

from statistics import NormalDist
import math

from config import (
    SIGMA_ENSEMBLE_INFLATION,
    CITY_SIGMA_CLIMO,
    SIGMA_MIN_EXACT,
    CITY_MIN_SIGMA,
)

# =========================================================
# TEMP
# =========================================================

def to_celsius(temp, unit="C"):

    if unit.upper() == "F":
        return (float(temp) - 32.0) * 5.0 / 9.0

    return float(temp)

# =========================================================
# SIGMA
# =========================================================

def build_sigma(city_slug: str,
                forecast_day: int,
                raw_sigma: float,
                condition: str = ""):

    sigma_used = max(float(raw_sigma), 0.10)

    inflation = SIGMA_ENSEMBLE_INFLATION.get(
        forecast_day,
        2.0
    )

    sigma_ens = sigma_used * inflation

    sigma_clim = CITY_SIGMA_CLIMO.get(
        city_slug,
        2.0
    )

    sigma_total = math.sqrt(
        (sigma_ens ** 2)
        + (sigma_clim ** 2)
    )

    # =====================================================
    # EXACT → sigma mínimo
    # =====================================================

    if condition.upper() == "EXACT":

        if sigma_total < SIGMA_MIN_EXACT:

            print(
                f"  [sigma] {city_slug} EXACT: "
                f"sigma {sigma_total:.2f} "
                f"→ {SIGMA_MIN_EXACT:.2f} "
                f"(min_exact)"
            )

            sigma_total = SIGMA_MIN_EXACT

    # =====================================================
    # CITY MIN
    # =====================================================

    city_min = CITY_MIN_SIGMA.get(city_slug)

    if city_min and sigma_total < city_min:

        print(
            f"  [sigma] {city_slug}: "
            f"sigma {sigma_total:.2f} "
            f"→ {city_min:.2f} "
            f"(city_min)"
        )

        sigma_total = city_min

    return round(sigma_total, 4)

# =========================================================
# PROBABILIDADE
# =========================================================

def calculate_probability(
    forecast_c: float,
    sigma: float,
    target: float,
    condition: str,
    unit: str = "C"
):

    target_c = to_celsius(target, unit)

    dist = NormalDist(
        mu=float(forecast_c),
        sigma=max(float(sigma), 0.10)
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

        lower = target_c - half_window_c
        upper = target_c + half_window_c

        prob = (
            dist.cdf(upper)
            - dist.cdf(lower)
        )

        return round(prob, 4)

    return 0.0
