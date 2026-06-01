# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""
simulate.py — Backtest e análise de performance do Weather Quant Bot.

Funcionalidades:
  1. Métricas de performance: Sharpe, Sortino, Profit Factor, Max Drawdown
  2. Sensitivity analysis: varre parâmetros (min_prob, min_zscore, kelly_fraction)
  3. Calibration plot: prob modelo vs win rate real (reliability diagram)
  4. Monte Carlo: simula distribuições de trajetórias futuras
  5. Rolling metrics: evolução temporal de win rate, edge realizado

Uso:
    python simulate.py              # Relatório completo
    python simulate.py --param      # Só sensitivity analysis
    python simulate.py --monte      # Só Monte Carlo (1000 simulações)
    python simulate.py --csv        # Exporta trades para CSV
"""

import json
import sys
import math
import random
from collections import defaultdict
from datetime import datetime
from pathlib import Path

BANKROLL_FILE = Path("bankroll.json")


# ══════════════════════════════════════════════════════════════════════════════
# CARREGAMENTO
# ══════════════════════════════════════════════════════════════════════════════

def load_trades():
    data = json.loads(BANKROLL_FILE.read_text(encoding="utf-8"))
    history  = data.get("history", [])
    balance  = float(data.get("balance", 0))
    start    = float(data.get("start_balance", 100))
    closed   = [t for t in history if t.get("result") in ("WIN", "LOSS")]
    open_t   = [t for t in history if t.get("result") == "OPEN"]
    closed.sort(key=lambda t: t.get("exit_time") or "")
    return data, closed, open_t, balance, start


# ══════════════════════════════════════════════════════════════════════════════
# MÉTRICAS CORE
# ══════════════════════════════════════════════════════════════════════════════

def pnl_series(closed, start_balance):
    """Retorna série de (data, saldo) construída cronologicamente."""
    series = [(None, start_balance)]
    running = start_balance
    for t in closed:
        running += float(t.get("pnl") or 0)
        series.append((t.get("exit_time", "")[:10], round(running, 4)))
    return series


def max_drawdown(series):
    """Max drawdown em % sobre o pico anterior."""
    peak = series[0][1]
    mdd  = 0.0
    for _, val in series:
        if val > peak:
            peak = val
        dd = (peak - val) / peak if peak > 0 else 0
        mdd = max(mdd, dd)
    return round(mdd * 100, 2)


def sharpe_ratio(closed, risk_free=0.0):
    """Sharpe diário simplificado sobre retornos por trade."""
    if len(closed) < 2:
        return None
    returns = [float(t.get("pnl") or 0) / float(t.get("stake") or 1) for t in closed]
    n   = len(returns)
    mu  = sum(returns) / n
    var = sum((r - mu) ** 2 for r in returns) / (n - 1)
    std = math.sqrt(var) if var > 0 else 0
    return round((mu - risk_free) / std, 3) if std > 0 else None


def sortino_ratio(closed, risk_free=0.0):
    """Sortino: só desvio dos retornos negativos."""
    if len(closed) < 2:
        return None
    returns  = [float(t.get("pnl") or 0) / float(t.get("stake") or 1) for t in closed]
    mu       = sum(returns) / len(returns)
    downside = [r for r in returns if r < risk_free]
    if not downside:
        return None
    ds_var = sum((r - risk_free) ** 2 for r in downside) / len(downside)
    ds_std = math.sqrt(ds_var)
    return round((mu - risk_free) / ds_std, 3) if ds_std > 0 else None


def profit_factor(closed):
    """Gross Wins / Gross Losses (>1 = rentável)."""
    gross_win  = sum(float(t.get("pnl") or 0) for t in closed if t.get("result") == "WIN")
    gross_loss = sum(abs(float(t.get("pnl") or 0)) for t in closed if t.get("result") == "LOSS")
    if gross_loss == 0:
        return None
    return round(gross_win / gross_loss, 3)


def brier_score(closed):
    vals = [
        (float(t.get("model_prob") or 0) - (1.0 if t.get("result") == "WIN" else 0.0)) ** 2
        for t in closed if t.get("model_prob") is not None
    ]
    return round(sum(vals) / len(vals), 4) if vals else None


def expected_calibration_error(closed, n_bins=5):
    """
    ECE — média ponderada da diferença entre prob prevista e win rate real
    por bin. Quanto menor, mais calibrado o modelo (0 = perfeito).
    """
    if not closed:
        return None
    bins = defaultdict(list)
    for t in closed:
        prob = t.get("model_prob")
        if prob is None:
            continue
        b = min(int(prob * n_bins), n_bins - 1)
        bins[b].append(1.0 if t.get("result") == "WIN" else 0.0)

    ece = 0.0
    n   = len(closed)
    for b, outcomes in bins.items():
        mid       = (b + 0.5) / n_bins
        actual_wr = sum(outcomes) / len(outcomes)
        ece      += (len(outcomes) / n) * abs(mid - actual_wr)
    return round(ece, 4)


def edge_realizado(closed):
    vals = [
        (1.0 if t.get("result") == "WIN" else 0.0) - float(t.get("model_prob") or 0)
        for t in closed if t.get("model_prob") is not None
    ]
    return round(sum(vals) / len(vals) * 100, 2) if vals else None


# ══════════════════════════════════════════════════════════════════════════════
# RELIABILITY DIAGRAM (calibração)
# ══════════════════════════════════════════════════════════════════════════════

def calibration_table(closed, n_bins=5):
    """
    Reliability diagram em texto.
    Compara probabilidade prevista com taxa de acerto real por faixa.
    Modelo bem calibrado → win rate ≈ prob prevista em cada bin.
    """
    bins = defaultdict(list)
    for t in closed:
        prob = t.get("model_prob")
        if prob is None:
            continue
        b = min(int(float(prob) * n_bins), n_bins - 1)
        bins[b].append(t)

    lines = [
        "",
        "RELIABILITY DIAGRAM (calibração do modelo)",
        f"{'Faixa de Prob':>18} {'N':>4} {'Win%':>6} {'Previsto':>8} {'Desvio':>8}",
        "-" * 50,
    ]
    for b in range(n_bins):
        trades = bins.get(b, [])
        lo = b / n_bins * 100
        hi = (b + 1) / n_bins * 100
        if not trades:
            lines.append(f"  {lo:.0f}%–{hi:.0f}%             (sem dados)")
            continue
        mid     = (lo + hi) / 2
        wins    = sum(1 for t in trades if t.get("result") == "WIN")
        wr      = wins / len(trades) * 100
        desvio  = wr - mid
        sinal   = "+" if desvio >= 0 else ""
        flag    = "⚠" if abs(desvio) > 15 else "✓"
        lines.append(
            f"  {lo:.0f}%–{hi:.0f}%"
            f"  {len(trades):>4}"
            f"  {wr:>5.1f}%"
            f"  {mid:>7.1f}%"
            f"  {sinal}{desvio:>6.1f}% {flag}"
        )
    lines.append(
        "\n  ✓ = desvio ≤ 15pp   ⚠ = desvio > 15pp (modelo mal calibrado nesta faixa)"
    )
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# SENSITIVITY ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

def _apply_filters(closed, min_prob, min_edge, kelly_fraction):
    """Simula filtragem retroativa com parâmetros alternativos."""
    filtered = []
    for t in closed:
        prob  = float(t.get("model_prob") or 0)
        edge  = float(t.get("edge") or 0)
        stake = float(t.get("stake") or 0)
        price = float(t.get("market_price") or 0.5)

        if prob < min_prob:
            continue
        if edge < min_edge:
            continue

        # Recalcula stake com kelly_fraction alternativa
        b = (1.0 / price) - 1.0 if price > 0 else 0
        q = 1.0 - prob
        kelly_pct = max(0.0, (prob * b - q) / b) if b > 0 else 0
        new_stake = min(kelly_pct * kelly_fraction * 100, 2.0)

        # Escala o PnL proporcionalmente ao novo stake
        scale = new_stake / stake if stake > 0 else 1.0
        new_pnl = float(t.get("pnl") or 0) * scale

        filtered.append({**t, "stake": new_stake, "pnl": new_pnl})
    return filtered


def sensitivity_analysis(closed, start_balance=100.0):
    """Varre combinações de parâmetros e exibe tabela de resultados."""
    if len(closed) < 5:
        return "\nSensitivity analysis: poucos trades fechados (mínimo 5).\n"

    min_probs    = [0.60, 0.65, 0.70, 0.75, 0.80]
    kelly_fracs  = [0.25, 0.50, 0.75]

    lines = [
        "",
        "SENSITIVITY ANALYSIS (parâmetros vs performance)",
        f"{'min_prob':>10} {'kelly':>6} {'N':>4} {'PnL':>7} {'WR%':>6} {'PF':>6} {'MDD%':>6}",
        "-" * 52,
    ]

    best_pnl = float("-inf")
    best_row = ""

    for min_prob in min_probs:
        for kf in kelly_fracs:
            filtered = _apply_filters(closed, min_prob, 0.02, kf)
            if not filtered:
                continue
            wins   = [t for t in filtered if t.get("result") == "WIN"]
            losses = [t for t in filtered if t.get("result") == "LOSS"]
            n      = len(filtered)
            wr     = len(wins) / n * 100 if n else 0
            pnl    = sum(float(t.get("pnl") or 0) for t in filtered)
            series = pnl_series(filtered, start_balance)
            mdd    = max_drawdown(series)
            pf     = profit_factor(filtered)
            pf_str = f"{pf:.2f}" if pf is not None else "N/A"
            marker = " ←" if pnl > best_pnl else ""
            if pnl > best_pnl:
                best_pnl = pnl

            row = (
                f"  {min_prob:.2f}     {kf:.2f}"
                f"  {n:>4}"
                f"  {'+' if pnl >= 0 else ''}${abs(pnl):>5.2f}"
                f"  {wr:>5.1f}%"
                f"  {pf_str:>6}"
                f"  {mdd:>5.1f}%"
                f"{marker}"
            )
            lines.append(row)
            if marker:
                best_row = row

    lines.append(
        "\n  ← Melhor PnL observado. ATENÇÃO: backtest em dados usados para tuning"
        "\n    (overfitting possível). Validar em trades futuros."
    )
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# ROLLING METRICS
# ══════════════════════════════════════════════════════════════════════════════

def rolling_winrate(closed, window=10):
    """Win rate nos últimos N trades (deslizante)."""
    if len(closed) < window:
        return None
    recent = closed[-window:]
    wins   = sum(1 for t in recent if t.get("result") == "WIN")
    return round(wins / window * 100, 1)


def per_city_stats(closed):
    stats = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0.0, "stakes": []})
    for t in closed:
        city = t.get("city", "?")
        if t.get("result") == "WIN":
            stats[city]["wins"] += 1
        else:
            stats[city]["losses"] += 1
        stats[city]["pnl"]    += float(t.get("pnl") or 0)
        stats[city]["stakes"].append(float(t.get("stake") or 0))
    return stats


def per_type_stats(closed):
    stats = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0.0})
    for t in closed:
        tp = t.get("type", "?").upper()
        if t.get("result") == "WIN":
            stats[tp]["wins"] += 1
        else:
            stats[tp]["losses"] += 1
        stats[tp]["pnl"] += float(t.get("pnl") or 0)
    return stats


# ══════════════════════════════════════════════════════════════════════════════
# MONTE CARLO
# ══════════════════════════════════════════════════════════════════════════════

def monte_carlo(closed, start_balance, n_sim=1000, n_trades=50, seed=42):
    """
    Simula n_sim trajetórias de n_trades trades sortendo com reposição
    do histórico fechado. Retorna percentis de saldo final.
    """
    if len(closed) < 5:
        return "\nMonte Carlo: poucos trades fechados (mínimo 5).\n"

    random.seed(seed)
    returns = [float(t.get("pnl") or 0) for t in closed]
    finals  = []

    for _ in range(n_sim):
        bal = start_balance
        for pnl in random.choices(returns, k=n_trades):
            bal += pnl
        finals.append(bal)

    finals.sort()
    p5   = finals[int(0.05 * n_sim)]
    p25  = finals[int(0.25 * n_sim)]
    p50  = finals[int(0.50 * n_sim)]
    p75  = finals[int(0.75 * n_sim)]
    p95  = finals[int(0.95 * n_sim)]
    prob_ruin = sum(1 for f in finals if f <= 0) / n_sim * 100
    prob_profit = sum(1 for f in finals if f > start_balance) / n_sim * 100

    lines = [
        "",
        f"MONTE CARLO — {n_sim} simulações × {n_trades} trades",
        f"  Saldo inicial: ${start_balance:.2f}",
        f"  Saldo mediano (p50): ${p50:.2f}",
        "",
        f"  Percentil  5%  (pessimista):  ${p5:.2f}",
        f"  Percentil 25%:                ${p25:.2f}",
        f"  Percentil 50% (mediana):      ${p50:.2f}",
        f"  Percentil 75%:                ${p75:.2f}",
        f"  Percentil 95%  (otimista):    ${p95:.2f}",
        "",
        f"  Prob. de lucro (> ${start_balance:.0f}): {prob_profit:.1f}%",
        f"  Prob. de ruína (≤ $0):         {prob_ruin:.1f}%",
        "",
        "  NOTA: simulação usa distribuição empírica de PnL (bootstrap com",
        "  reposição). Com N < 50 trades, resultados têm alta variância.",
    ]
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# EXPORT CSV
# ══════════════════════════════════════════════════════════════════════════════

def export_csv(closed, path="trades_export.csv"):
    fields = [
        "city", "market_date", "type", "unit", "target", "forecast_c",
        "model_prob", "market_price", "edge", "ev", "stake", "shares",
        "result", "pnl", "fee", "real_temp_c", "sigma_total", "forecast_day",
        "entry_time", "exit_time",
    ]
    lines = [",".join(fields)]
    for t in closed:
        row = []
        for f in fields:
            v = t.get(f, "")
            if isinstance(v, float):
                row.append(f"{v:.4f}")
            else:
                row.append(str(v) if v is not None else "")
        lines.append(",".join(row))
    Path(path).write_text("\n".join(lines), encoding="utf-8")
    print(f"Exportado: {path} ({len(closed)} trades)")


# ══════════════════════════════════════════════════════════════════════════════
# RELATÓRIO COMPLETO
# ══════════════════════════════════════════════════════════════════════════════

def full_report():
    data, closed, open_t, balance, start = load_trades()
    n = len(closed)

    print("=" * 60)
    print("WEATHER QUANT BOT — SIMULATION & PERFORMANCE REPORT")
    import sys, io
    if hasattr(sys.stdout, 'reconfigure'):
        try: sys.stdout.reconfigure(encoding='utf-8')
        except Exception: pass
    print(f"Gerado em: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    # ── Overview ──────────────────────────────────────────────
    wins   = [t for t in closed if t.get("result") == "WIN"]
    losses = [t for t in closed if t.get("result") == "LOSS"]
    pnl_total = sum(float(t.get("pnl") or 0) for t in closed)

    print(f"\nBANKROLL")
    print(f"  Saldo atual:     ${balance:.2f}")
    print(f"  Saldo inicial:   ${start:.2f}")
    print(f"  PnL total:       ${pnl_total:+.2f} ({(pnl_total/start*100):+.1f}%)")
    print(f"  Trades fechados: {n}  ({len(wins)}W / {len(losses)}L)")
    print(f"  Trades abertos:  {len(open_t)}")
    exposure = sum(float(t.get("stake") or 0) for t in open_t)
    print(f"  Exposição atual: ${exposure:.2f}")

    if n < 2:
        print("\nPoucos trades fechados para análise estatística.")
        return

    wr = len(wins) / n * 100

    # ── Métricas de performance ───────────────────────────────
    series  = pnl_series(closed, start)
    mdd     = max_drawdown(series)
    sharpe  = sharpe_ratio(closed)
    sortino = sortino_ratio(closed)
    pf      = profit_factor(closed)
    brier   = brier_score(closed)
    ece     = expected_calibration_error(closed)
    edge_r  = edge_realizado(closed)
    wr10    = rolling_winrate(closed, 10)

    print(f"\nMÉTRICAS DE PERFORMANCE")
    print(f"  Win rate:          {wr:.1f}%")
    print(f"  Win rate (últ 10): {wr10:.1f}%" if wr10 is not None else "  Win rate (últ 10): N/A")
    print(f"  Profit Factor:     {pf:.3f}" if pf is not None else "  Profit Factor:     N/A")
    print(f"  Max Drawdown:      {mdd:.1f}%")
    print(f"  Sharpe ratio:      {sharpe:.3f}" if sharpe is not None else "  Sharpe ratio:      N/A")
    print(f"  Sortino ratio:     {sortino:.3f}" if sortino is not None else "  Sortino ratio:     N/A")

    print(f"\nCALIBRAÇÃO DO MODELO")
    print(f"  Brier score:       {brier:.4f}  (0=perfeito, 0.25=inútil)" if brier is not None else "  Brier score:       N/A")
    print(f"  ECE:               {ece:.4f}  (0=perfeito)" if ece is not None else "  ECE:               N/A")
    print(f"  Edge realizado:    {edge_r:+.1f}% (positivo = modelo subestima)" if edge_r is not None else "  Edge realizado:    N/A")

    # Interpretação
    if brier is not None:
        if brier < 0.15:
            print("  → Modelo bem calibrado")
        elif brier < 0.25:
            print("  → Calibração aceitável")
        else:
            print("  → ⚠ Modelo mal calibrado — probabilidades não refletem realidade")

    if pf is not None:
        if pf > 1.5:
            print(f"  → Profit Factor {pf:.2f}: sistema rentável")
        elif pf > 1.0:
            print(f"  → Profit Factor {pf:.2f}: levemente positivo")
        else:
            print(f"  → ⚠ Profit Factor {pf:.2f}: sistema perdedor")

    # ── Por cidade ─────────────────────────────────────────────
    city_stats = per_city_stats(closed)
    print(f"\nPOR CIDADE (min 2 trades)")
    print(f"  {'Cidade':>18} {'N':>4} {'WR%':>6} {'PnL':>8} {'Avg Stake':>10}")
    print("  " + "-" * 52)
    ranked = sorted(city_stats.items(), key=lambda x: -(x[1]["wins"] + x[1]["losses"]))
    for city, s in ranked:
        nt = s["wins"] + s["losses"]
        if nt < 2:
            continue
        city_wr = s["wins"] / nt * 100
        avg_stake = sum(s["stakes"]) / len(s["stakes"]) if s["stakes"] else 0
        pnl_flag = "🟢" if s["pnl"] >= 0 else "🔴"
        print(
            f"  {city:>18}  {nt:>3}  {city_wr:>5.1f}%  "
            f"{pnl_flag}${s['pnl']:>+6.2f}  ${avg_stake:.2f}"
        )

    # ── Por tipo ───────────────────────────────────────────────
    type_stats = per_type_stats(closed)
    if type_stats:
        print(f"\nPOR TIPO DE MERCADO")
        for tp, s in sorted(type_stats.items()):
            nt = s["wins"] + s["losses"]
            if nt == 0:
                continue
            tp_wr = s["wins"] / nt * 100
            print(
                f"  {tp:6}  {nt} trades  WR {tp_wr:.1f}%  "
                f"PnL ${s['pnl']:+.2f}"
            )

    # ── Calibração ─────────────────────────────────────────────
    print(calibration_table(closed))

    # ── Sensitivity ────────────────────────────────────────────
    print(sensitivity_analysis(closed, start))

    # ── Monte Carlo ────────────────────────────────────────────
    print(monte_carlo(closed, start, n_sim=1000, n_trades=50))

    # ── Alertas ───────────────────────────────────────────────
    alerts = []
    if mdd > 50:
        alerts.append(f"⚠ Max drawdown {mdd:.1f}% — risco elevado")
    if brier is not None and brier >= 0.25:
        alerts.append(f"⚠ Brier {brier:.4f} ≥ 0.25 — modelo mal calibrado")
    if pf is not None and pf < 1.0:
        alerts.append(f"⚠ Profit Factor {pf:.2f} < 1.0 — sistema perdedor")
    if wr < 40:
        alerts.append(f"⚠ Win rate {wr:.1f}% muito baixo")
    if ece is not None and ece > 0.15:
        alerts.append(f"⚠ ECE {ece:.4f} > 0.15 — calibração pobre")

    if alerts:
        print(f"\n⚠ ALERTAS")
        for a in alerts:
            print(f"  {a}")
    else:
        print(f"\n✅ Nenhum alerta crítico")

    print("\n" + "=" * 60)


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    args = sys.argv[1:]

    if "--csv" in args:
        _, closed, _, _, _ = load_trades()
        export_csv(closed)
    elif "--param" in args:
        _, closed, _, balance, start = load_trades()
        print(sensitivity_analysis(closed, start))
    elif "--monte" in args:
        _, closed, _, balance, start = load_trades()
        print(monte_carlo(closed, start, n_sim=2000, n_trades=100))
    else:
        full_report()
