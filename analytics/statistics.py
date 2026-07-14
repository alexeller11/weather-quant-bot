"""
analytics.statistics

Métricas estatísticas do modelo probabilístico.

Este módulo NÃO mede lucro.

Ele mede se as probabilidades produzidas pelo modelo
estão corretas.

Todas as funções recebem TradeDataset.
"""

from __future__ import annotations

import math
from collections import defaultdict
from statistics import mean

from .dataset import TradeDataset


# ============================================================
# Helpers
# ============================================================

def resolved(dataset: TradeDataset):
    """
    Apenas trades resolvidos (WIN/LOSS).
    """
    return dataset.wins + dataset.losses


def probabilities(dataset: TradeDataset):

    values = []

    for trade in resolved(dataset):

        p = trade.get("model_prob")

        if p is None:
            p = trade.get("probability")

        if p is None:
            continue

        try:
            values.append(float(p))
        except Exception:
            pass

    return values


def outcomes(dataset: TradeDataset):

    values = []

    for trade in resolved(dataset):

        if trade.get("result") == "WIN":
            values.append(1.0)
        else:
            values.append(0.0)

    return values


# ============================================================
# Brier Score
# ============================================================

def brier_score(dataset: TradeDataset):

    probs = probabilities(dataset)

    actual = outcomes(dataset)

    if not probs:
        return 0.0

    return sum(

        (p-a)**2

        for p, a in zip(probs, actual)

    ) / len(probs)


# ============================================================
# Log Loss
# ============================================================

def log_loss(dataset: TradeDataset):

    probs = probabilities(dataset)

    actual = outcomes(dataset)

    if not probs:
        return 0.0

    eps = 1e-15

    total = 0.0

    for p, y in zip(probs, actual):

        p = min(max(p, eps), 1-eps)

        total += (

            y*math.log(p)

            +

            (1-y)*math.log(1-p)

        )

    return -total/len(probs)


# ============================================================
# Calibration
# ============================================================

def calibration_bins(dataset: TradeDataset, bins=10):

    bucket = defaultdict(list)

    probs = probabilities(dataset)

    actual = outcomes(dataset)

    for p, y in zip(probs, actual):

        idx = min(

            int(p*bins),

            bins-1

        )

        bucket[idx].append((p, y))

    return bucket


def calibration_curve(dataset: TradeDataset, bins=10):

    result = []

    buckets = calibration_bins(dataset, bins)

    for idx in range(bins):

        values = buckets.get(idx)

        if not values:
            continue

        p = mean(v[0] for v in values)

        y = mean(v[1] for v in values)

        result.append({

            "bin": idx,

            "predicted": p,

            "observed": y,

            "samples": len(values)

        })

    return result


# ============================================================
# Calibration Error
# ============================================================

def expected_calibration_error(dataset: TradeDataset, bins=10):

    curve = calibration_curve(dataset, bins)

    total = sum(

        c["samples"]

        for c in curve

    )

    if total == 0:

        return 0.0

    ece = 0.0

    for row in curve:

        ece += (

            abs(

                row["predicted"]

                -

                row["observed"]

            )

            *

            row["samples"]

            /

            total

        )

    return ece


# ============================================================
# Sharpness
# ============================================================

def sharpness(dataset: TradeDataset):

    probs = probabilities(dataset)

    if not probs:

        return 0.0

    return mean(

        abs(

            p-0.5

        )

        for p in probs

    )


# ============================================================
# Entropy
# ============================================================

def entropy(dataset: TradeDataset):

    probs = probabilities(dataset)

    if not probs:

        return 0.0

    eps = 1e-15

    values = []

    for p in probs:

        p = min(max(p, eps), 1-eps)

        values.append(

            -p*math.log2(p)

            -

            (1-p)*math.log2(1-p)

        )

    return mean(values)


# ============================================================
# Bias
# ============================================================

def prediction_bias(dataset: TradeDataset):

    probs = probabilities(dataset)

    actual = outcomes(dataset)

    if not probs:

        return 0.0

    return mean(

        p-a

        for p, a in zip(probs, actual)

    )


# ============================================================
# Confidence
# ============================================================

def average_confidence(dataset: TradeDataset):

    probs = probabilities(dataset)

    if not probs:

        return 0.0

    return mean(

        max(

            p,

            1-p

        )

        for p in probs

    )


# ============================================================
# Summary
# ============================================================

def summary(dataset: TradeDataset):

    return {

        "brier": brier_score(dataset),

        "log_loss": log_loss(dataset),

        "ece": expected_calibration_error(dataset),

        "sharpness": sharpness(dataset),

        "entropy": entropy(dataset),

        "bias": prediction_bias(dataset),

        "confidence": average_confidence(dataset),

        "calibration": calibration_curve(dataset),

    }
