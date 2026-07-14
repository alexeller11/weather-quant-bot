"""
analytics.score

Score Engine do Weather Quant.

Transforma métricas em uma nota de qualidade de 0 a 100.

Não calcula ROI.
Não calcula Brier.
Não calcula Sharpe.

Esses valores já vêm de finance.py e statistics.py.
"""

from __future__ import annotations

from typing import Dict


# ---------------------------------------------------------
# Configuração
# ---------------------------------------------------------

DEFAULT_WEIGHTS = {

    "roi": 0.30,

    "brier": 0.20,

    "profit_factor": 0.15,

    "drawdown": 0.10,

    "win_rate": 0.10,

    "sharpe": 0.10,

    "sample_size": 0.05,
}


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def clamp(value, minimum=0.0, maximum=100.0):

    return max(minimum, min(maximum, value))


def normalize_positive(value, target):

    """
    Quanto maior melhor.

    target = valor considerado excelente.
    """

    if target <= 0:

        return 0.0

    return clamp(

        value / target * 100

    )


def normalize_negative(value, limit):

    """
    Quanto menor melhor.

    Ex.: drawdown, brier.
    """

    if limit <= 0:

        return 100.0

    return clamp(

        (1 - value / limit) * 100

    )


# ---------------------------------------------------------
# Score
# ---------------------------------------------------------

def score(metrics: Dict, weights=None):

    if weights is None:

        weights = DEFAULT_WEIGHTS

    roi = normalize_positive(

        metrics.get("roi", 0),

        0.20

    )

    brier = normalize_negative(

        metrics.get("brier", 1),

        0.25

    )

    pf = normalize_positive(

        metrics.get("profit_factor", 0),

        2.0

    )

    dd = normalize_negative(

        metrics.get("max_drawdown", 1),

        0.25

    )

    wr = normalize_positive(

        metrics.get("win_rate", 0),

        0.70

    )

    sharpe = normalize_positive(

        metrics.get("sharpe", 0),

        2.0

    )

    trades = normalize_positive(

        metrics.get("trades", 0),

        100

    )

    final = (

        roi * weights["roi"]

        +

        brier * weights["brier"]

        +

        pf * weights["profit_factor"]

        +

        dd * weights["drawdown"]

        +

        wr * weights["win_rate"]

        +

        sharpe * weights["sharpe"]

        +

        trades * weights["sample_size"]

    )

    return round(

        clamp(final),

        2

    )


# ---------------------------------------------------------
# Kelly Factor
# ---------------------------------------------------------

def kelly_factor(score_value):

    if score_value >= 90:

        return 1.00

    if score_value >= 80:

        return 0.80

    if score_value >= 70:

        return 0.60

    if score_value >= 60:

        return 0.40

    if score_value >= 50:

        return 0.20

    return 0.0


# ---------------------------------------------------------
# Status
# ---------------------------------------------------------

def status(score_value):

    if score_value >= 90:

        return "GREEN"

    if score_value >= 75:

        return "YELLOW"

    if score_value >= 60:

        return "ORANGE"

    if score_value >= 40:

        return "RED"

    return "BLACK"


# ---------------------------------------------------------
# Recommendation
# ---------------------------------------------------------

def recommendation(score_value):

    if score_value >= 90:

        return "Operação normal."

    if score_value >= 75:

        return "Operar normalmente, monitorar."

    if score_value >= 60:

        return "Reduzir Kelly."

    if score_value >= 40:

        return "Paper Trading."

    return "Parar operações."


# ---------------------------------------------------------
# Build
# ---------------------------------------------------------

def build(metrics):

    s = score(metrics)

    return {

        "score": s,

        "status": status(s),

        "kelly_factor": kelly_factor(s),

        "recommendation": recommendation(s),

    }
