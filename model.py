# =========================================================
# WEATHER QUANT BOT — MODEL (CORRIGIDO v3)
# FIX CRÍTICO: build_sigma() retornava None apenas para EXACT
#              com sigma baixo. O cap SIGMA_MAX_ABOVE_BELOW=3.6
#              existia mas o código nunca retornava None para
#              ABOVE/BELOW acima do cap — apenas logava e
#              continuava. Corrigido: retorna None em todos os
#              casos acima do cap, bloqueando o trade em bot.py.
# =========================================================

from statistics import NormalDist

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

def to_celsius(temp, unit="C"):
    if unit.upper() == "F":
        return (float(temp) - 32.0) * 5.0 / 9.0
    return float(temp)

# =========================================================
# SIGMA
# =========================================================

def build_sigma(city_slug, forecast_day, raw_sigma, condition=""):
    """
    Calcula sigma total e aplica caps.

    Retorna None (bloqueio de trade) se:
      - sigma abaixo do mínimo para EXACT
      - sigma acima do cap para ABOVE/BELOW (SIGMA_MAX_ABOVE_BELOW)
      - sigma acima do cap para EXACT (SIGMA_MAX_EXACT)

    IMPORTANTE: retornar None aqui faz bot.py pular o mercado via:
        sigma_total = build_sigma(...)
        if sigma_total is None:
            continue
    """

    sigma_used = max(float(raw_sigma), 0.10)

    inflation = SIGMA_ENSEMBLE_INFLATION.get(forecast_day, 2.0)
    sigma_ens = sigma_used * inflation

    sigma_clim = CITY_SIGMA_CLIMO.get(city_slug, 2.0)

    # raw_sigma já representa incerteza do forecast.
    # O valor da cidade é um piso, não um erro independente.
    # Somar em quadratura era dupla contagem.
    sigma_total = max(sigma_ens, sigma_clim)

    condition_upper = condition.upper()

    # ── EXACT: rejeitar se sigma muito baixo ─────────────
    if condition_upper == "EXACT":
        if sigma_total < SIGMA_MIN_EXACT:
            print(
                f"  BLOQUEADO sigma muito baixo para EXACT "
                f"({sigma_total:.2f} < {SIGMA_MIN_EXACT:.2f})"
            )
            return None

    # ── Cidade tem mínimo próprio ─────────────────────────
    city_min = CITY_MIN_SIGMA.get(city_slug)
    if city_min and sigma_total < city_min:
        sigma_total = city_min

    # ── Cap por tipo — ACIMA DO CAP = BLOQUEIO ────────────
    sigma_cap = (
        SIGMA_MAX_EXACT
        if condition_upper == "EXACT"
        else SIGMA_MAX_ABOVE_BELOW
    )

    if sigma_total > sigma_cap:
        print(
            f"  BLOQUEADO sigma acima do cap "
            f"({sigma_total:.2f} > {sigma_cap:.2f}) "
            f"[{condition_upper}] {city_slug}"
        )
        return None  # FIX: antes só logava, não retornava None

    return round(sigma_total, 4)

# =========================================================
# PROBABILITY
# =========================================================

def calculate_probability(forecast_c, sigma, target, condition, unit="C"):
    if sigma is None:
        return 0.0

    target_c = to_celsius(target, unit)

    dist = NormalDist(
        mu=float(forecast_c),
        sigma=max(float(sigma), 0.10),
    )

    condition = condition.upper()

    if condition == "ABOVE":
        return round(1.0 - dist.cdf(target_c), 4)

    if condition == "BELOW":
        return round(dist.cdf(target_c), 4)

    if condition == "EXACT":
        if unit.upper() == "F":
            half_window_c = 0.2777777778
        else:
            half_window_c = 0.5

        prob = dist.cdf(target_c + half_window_c) - dist.cdf(target_c - half_window_c)
        return round(prob, 4)

    return 0.0
