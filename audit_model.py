"""
Model audit report for the weather paper-trading bot.

The report is intentionally local and deterministic: it reads bankroll.json and
flags calibration, exposure, sigma and probability-shape problems without
calling external APIs.
"""

import json
from collections import defaultdict
from pathlib import Path

from config import (
    MAX_TOTAL_EXPOSURE,
    PROBABILITY_DEAD_ZONE_LOW,
    PROBABILITY_DEAD_ZONE_HIGH,
    SIGMA_MAX_ABOVE_BELOW,
)


BANKROLL_FILE = Path("bankroll.json")


def _pct(value):
    return f"{value * 100:.1f}%"


def load_history():
    data = json.loads(BANKROLL_FILE.read_text(encoding="utf-8"))
    return data, data.get("history", [])


def summarize():
    data, history = load_history()
    closed = [t for t in history if t.get("result") in ("WIN", "LOSS")]
    open_trades = [t for t in history if t.get("result") == "OPEN"]
    voided = [t for t in history if t.get("result") == "VOID"]
    wins = [t for t in closed if t.get("result") == "WIN"]

    closed_pnl = sum(float(t.get("pnl") or 0) for t in closed)
    open_exposure = sum(float(t.get("stake") or 0) for t in open_trades)
    brier_values = [
        (float(t.get("model_prob")) - (1.0 if t.get("result") == "WIN" else 0.0)) ** 2
        for t in closed
        if t.get("model_prob") is not None
    ]
    brier = sum(brier_values) / len(brier_values) if brier_values else None

    active_flags = []
    historical_flags = []
    for trade in history:
        prob = trade.get("model_prob")
        sigma = trade.get("sigma_total")
        bucket = active_flags if trade.get("result") == "OPEN" else historical_flags
        if prob is not None and PROBABILITY_DEAD_ZONE_LOW <= float(prob) <= PROBABILITY_DEAD_ZONE_HIGH:
            bucket.append((trade, "probability dead zone"))
        if sigma is not None and float(sigma) > SIGMA_MAX_ABOVE_BELOW:
            bucket.append((trade, "sigma too high"))

    by_type = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0.0})
    by_city = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0.0})

    for trade in closed:
        result_key = "wins" if trade.get("result") == "WIN" else "losses"
        by_type[trade.get("type", "?")][result_key] += 1
        by_type[trade.get("type", "?")]["pnl"] += float(trade.get("pnl") or 0)
        by_city[trade.get("city", "?")][result_key] += 1
        by_city[trade.get("city", "?")]["pnl"] += float(trade.get("pnl") or 0)

    lines = [
        "WEATHER QUANT BOT AUDIT",
        "=" * 24,
        f"Balance: ${float(data.get('balance', 0)):.2f}",
        f"Closed trades: {len(closed)} ({len(wins)}W/{len(closed) - len(wins)}L)",
        f"Open trades: {len(open_trades)}",
        f"Voided trades: {len(voided)}",
        f"Open exposure: ${open_exposure:.2f} / ${MAX_TOTAL_EXPOSURE:.2f}",
        f"Closed PnL: ${closed_pnl:+.2f}",
    ]

    if closed:
        lines.append(f"Win rate: {_pct(len(wins) / len(closed))}")
    if brier is not None:
        lines.append(f"Brier score: {brier:.4f}")

    lines.append("")
    lines.append("By type:")
    for key, stats in sorted(by_type.items()):
        total = stats["wins"] + stats["losses"]
        wr = stats["wins"] / total if total else 0
        lines.append(
            f"  {key:6} {stats['wins']}W/{stats['losses']}L "
            f"({_pct(wr)}) PnL ${stats['pnl']:+.2f}"
        )

    lines.append("")
    lines.append("Top cities:")
    ranked_cities = sorted(
        by_city.items(),
        key=lambda item: item[1]["wins"] + item[1]["losses"],
        reverse=True,
    )[:8]
    for key, stats in ranked_cities:
        total = stats["wins"] + stats["losses"]
        wr = stats["wins"] / total if total else 0
        lines.append(
            f"  {key:15} {stats['wins']}W/{stats['losses']}L "
            f"({_pct(wr)}) PnL ${stats['pnl']:+.2f}"
        )

    lines.append("")
    lines.append("Open flags:")
    if not active_flags:
        lines.append("  none")
    else:
        for trade, reason in active_flags[:20]:
            lines.append(
                f"  {reason}: {trade.get('city')} {trade.get('type')} "
                f"{trade.get('target')} prob={trade.get('model_prob')} "
                f"sigma={trade.get('sigma_total')}"
            )

    lines.append("")
    lines.append("Historical flags:")
    if not historical_flags:
        lines.append("  none")
    else:
        for trade, reason in historical_flags[:20]:
            lines.append(
                f"  {reason}: {trade.get('city')} {trade.get('type')} "
                f"{trade.get('target')} prob={trade.get('model_prob')} "
                f"sigma={trade.get('sigma_total')}"
            )

    return "\n".join(lines)


if __name__ == "__main__":
    print(summarize())
