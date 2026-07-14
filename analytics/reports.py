"""
analytics.reports

Gerador de relatórios do Quant Intelligence Engine.

Este módulo NÃO envia mensagens.
Ele apenas gera textos.

Pode ser usado por:

- Telegram
- Discord
- Dashboard
- API
- CLI
"""

from __future__ import annotations

from datetime import datetime


# ============================================================
# Helpers
# ============================================================

def pct(value):

    if value is None:
        return "-"

    return f"{value*100:.2f}%"


def num(value):

    if value is None:
        return "-"

    if isinstance(value, float):

        return f"{value:.2f}"

    return str(value)


def money(value):

    if value is None:

        return "-"

    return f"${value:,.2f}"


# ============================================================
# Rankings
# ============================================================

def _top(dictionary, n=5):

    if not dictionary:

        return []

    values = sorted(

        dictionary.items(),

        key=lambda x: x[1].get("roi", 0),

        reverse=True

    )

    return values[:n]


def _bottom(dictionary, n=5):

    if not dictionary:

        return []

    values = sorted(

        dictionary.items(),

        key=lambda x: x[1].get("roi", 0),

    )

    return values[:n]


# ============================================================
# Texto
# ============================================================

def text(report):

    analytics = report["analytics"]

    health = report["health"]

    finance = analytics["finance"]

    statistics = analytics["statistics"]

    performance = analytics["performance"]

    lines = []

    lines.append("=" * 60)

    lines.append("WEATHER QUANT ANALYTICS")

    lines.append("=" * 60)

    lines.append("")

    lines.append(f"Gerado: {datetime.utcnow().isoformat()} UTC")

    lines.append("")

    lines.append("GERAL")

    lines.append("-" * 60)

    lines.append(f"ROI................. {pct(finance['roi'])}")

    lines.append(f"Profit Factor....... {num(finance['profit_factor'])}")

    lines.append(f"Win Rate............ {pct(finance['win_rate'])}")

    lines.append(f"Expectancy.......... {money(finance['expectancy'])}")

    lines.append(f"Drawdown............ {pct(finance['max_drawdown'])}")

    lines.append(f"Sharpe.............. {num(finance['sharpe'])}")

    lines.append(f"Sortino............. {num(finance['sortino'])}")

    lines.append(f"Calmar.............. {num(finance['calmar'])}")

    lines.append("")

    lines.append("MODELO")

    lines.append("-" * 60)

    lines.append(f"Brier............... {num(statistics['brier'])}")

    lines.append(f"LogLoss............. {num(statistics['log_loss'])}")

    lines.append(f"ECE................. {num(statistics['ece'])}")

    lines.append(f"Sharpness........... {num(statistics['sharpness'])}")

    lines.append(f"Confidence.......... {pct(statistics['confidence'])}")

    lines.append("")

    lines.append("HEALTH")

    lines.append("-" * 60)

    lines.append(f"Status.............. {health['status']}")

    lines.append(f"Score............... {health['score']}")

    lines.append(f"Kelly............... {health['kelly_factor']}")

    lines.append(f"Paper Mode.......... {health['paper_mode']}")

    lines.append(f"Recommendation...... {health['recommendation']}")

    lines.append("")

    #
    # Top cidades
    #

    lines.append("TOP CIDADES")

    lines.append("-" * 60)

    for city, data in _top(

        performance["cities"]

    ):

        lines.append(

            f"{city:<20}"

            f"ROI={pct(data['roi'])}"

            f" PF={num(data['profit_factor'])}"

            f" Trades={data['trades']}"

        )

    lines.append("")

    lines.append("PIORES CIDADES")

    lines.append("-" * 60)

    for city, data in _bottom(

        performance["cities"]

    ):

        lines.append(

            f"{city:<20}"

            f"ROI={pct(data['roi'])}"

            f" PF={num(data['profit_factor'])}"

            f" Trades={data['trades']}"

        )

    lines.append("")

    #
    # Mercados
    #

    lines.append("MERCADOS")

    lines.append("-" * 60)

    for market, data in performance["markets"].items():

        lines.append(

            f"{market:<15}"

            f"ROI={pct(data['roi'])}"

            f" PF={num(data['profit_factor'])}"

        )

    lines.append("")

    #
    # Forecast
    #

    lines.append("FORECAST DAYS")

    lines.append("-" * 60)

    for day, data in performance["forecast_days"].items():

        lines.append(

            f"D+{day:<3}"

            f"ROI={pct(data['roi'])}"

            f" PF={num(data['profit_factor'])}"

        )

    lines.append("")

    #
    # Alertas
    #

    if health["alerts"]:

        lines.append("ALERTAS")

        lines.append("-" * 60)

        for alert in health["alerts"]:

            lines.append(f"• {alert}")

        lines.append("")

    return "\n".join(lines)


# ============================================================
# Markdown
# ============================================================

def markdown(report):

    analytics = report["analytics"]

    finance = analytics["finance"]

    health = report["health"]

    md = []

    md.append("# Weather Quant Report")

    md.append("")

    md.append("| Indicador | Valor |")

    md.append("|-----------|------:|")

    md.append(f"| ROI | {pct(finance['roi'])} |")

    md.append(f"| Profit Factor | {num(finance['profit_factor'])} |")

    md.append(f"| Win Rate | {pct(finance['win_rate'])} |")

    md.append(f"| Drawdown | {pct(finance['max_drawdown'])} |")

    md.append(f"| Health | {health['score']} |")

    md.append(f"| Status | {health['status']} |")

    md.append("")

    return "\n".join(md)


# ============================================================
# JSON
# ============================================================

def json(report):

    return report
