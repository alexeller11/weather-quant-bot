#!/usr/bin/env python3
"""
weekly_report.py — Relatório semanal automático de performance.

Enviado todo domingo via Telegram.
Inclui: Brier score, Sharpe, calibração, win rate, comparação semana anterior.
Roda via schedule no bot.py (toda domingo às 08:00 UTC).
"""

import json
import math
import os
from collections import defaultdict
from datetime import datetime, timezone, timedelta


# ── helpers ──────────────────────────────────────────────────

def _load_history():
    db_url = os.environ.get("DATABASE_URL", "")
    if db_url:
        try:
            import psycopg2
            conn = psycopg2.connect(db_url, sslmode="require")
            with conn.cursor() as cur:
                cur.execute("SELECT data FROM bankroll ORDER BY id DESC LIMIT 1")
                row = cur.fetchone()
            conn.close()
            if row:
                return row[0]
        except Exception:
            pass
    try:
        return json.load(open("bankroll.json", encoding="utf-8"))
    except Exception:
        return {"balance": 0, "start_balance": 200, "history": []}


def _brier(trades):
    vals = []
    for t in trades:
        prob = t.get("model_prob")
        side = (t.get("side") or "YES").upper()
        if prob is None:
            continue
        prob_aposta = (1 - prob) if side == "NO" else prob
        outcome = 1.0 if t["result"] == "WIN" else 0.0
        vals.append((prob_aposta - outcome) ** 2)
    return round(sum(vals) / len(vals), 4) if vals else None


def _sharpe(trades):
    if len(trades) < 2:
        return None
    returns = [float(t.get("pnl") or 0) / float(t.get("stake") or 1) for t in trades]
    mu = sum(returns) / len(returns)
    var = sum((r - mu) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(var) if var > 0 else 0
    return round(mu / std, 3) if std > 0 else None


def _profit_factor(trades):
    wins = sum(float(t.get("pnl") or 0) for t in trades if t["result"] == "WIN")
    losses = sum(abs(float(t.get("pnl") or 0)) for t in trades if t["result"] == "LOSS")
    return round(wins / losses, 2) if losses > 0 else None


def _calibration_text(trades):
    bins = defaultdict(list)
    for t in trades:
        prob = t.get("model_prob")
        side = (t.get("side") or "YES").upper()
        if prob is None:
            continue
        prob_aposta = (1 - prob) if side == "NO" else prob
        b = min(int(prob_aposta * 5), 4)
        bins[b].append(1.0 if t["result"] == "WIN" else 0.0)
    lines = []
    labels = ["0-20%", "20-40%", "40-60%", "60-80%", "80-100%"]
    for b in range(5):
        outcomes = bins.get(b, [])
        if not outcomes:
            continue
        wr = sum(outcomes) / len(outcomes) * 100
        mid = (b * 20 + 10)
        flag = "⚠" if abs(wr - mid) > 20 else "✓"
        lines.append(f"  {labels[b]}: {wr:.0f}% real vs {mid}% previsto {flag} (n={len(outcomes)})")
    return "\n".join(lines) if lines else "  sem dados"


def _by_city(trades):
    stats = defaultdict(lambda: {"w": 0, "l": 0, "pnl": 0.0})
    for t in trades:
        c = t.get("city", "?")
        if t["result"] == "WIN":
            stats[c]["w"] += 1
        else:
            stats[c]["l"] += 1
        stats[c]["pnl"] += float(t.get("pnl") or 0)
    ranked = sorted(stats.items(), key=lambda x: x[1]["pnl"], reverse=True)
    lines = []
    for city, s in ranked[:6]:
        n = s["w"] + s["l"]
        wr = s["w"] / n * 100 if n else 0
        em = "🟢" if s["pnl"] >= 0 else "🔴"
        lines.append(f"  {em} {city}: {s['w']}W/{s['l']}L ({wr:.0f}%) ${s['pnl']:+.2f}")
    return "\n".join(lines) if lines else "  sem dados"


def _by_type(trades):
    stats = defaultdict(lambda: {"w": 0, "l": 0, "pnl": 0.0})
    for t in trades:
        tp = (t.get("type") or "?").upper()
        if t["result"] == "WIN":
            stats[tp]["w"] += 1
        else:
            stats[tp]["l"] += 1
        stats[tp]["pnl"] += float(t.get("pnl") or 0)
    lines = []
    for tp, s in sorted(stats.items()):
        n = s["w"] + s["l"]
        wr = s["w"] / n * 100 if n else 0
        lines.append(f"  {tp}: {s['w']}W/{s['l']}L ({wr:.0f}%) ${s['pnl']:+.2f}")
    return "\n".join(lines) if lines else "  sem dados"


def _week_trades(history, weeks_ago=0):
    """Retorna trades fechados na semana N (0=esta semana, 1=semana passada)."""
    now = datetime.now(timezone.utc)
    week_start = now - timedelta(days=now.weekday() + 7 * weeks_ago)
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    week_end = week_start + timedelta(days=7)
    result = []
    for t in history:
        if t.get("result") not in ("WIN", "LOSS"):
            continue
        exit_str = t.get("exit_time", "")
        if not exit_str:
            mdate = t.get("market_date", "")
            if not mdate:
                continue
            exit_str = mdate + "T12:00:00+00:00"
        try:
            exit_dt = datetime.fromisoformat(exit_str.replace("Z", "+00:00"))
            if exit_dt.tzinfo is None:
                exit_dt = exit_dt.replace(tzinfo=timezone.utc)
            if week_start <= exit_dt < week_end:
                result.append(t)
        except Exception:
            continue
    return result


# ── relatório principal ───────────────────────────────────────

def gerar_relatorio_semanal(enviar_telegram=True):
    data = _load_history()
    history = data.get("history", [])
    balance = float(data.get("balance", 0))
    start_balance = float(data.get("start_balance", 200))

    closed_all = [t for t in history if t.get("result") in ("WIN", "LOSS")]
    open_trades = [t for t in history if t.get("result") == "OPEN"]

    this_week = _week_trades(history, 0)
    last_week = _week_trades(history, 1)

    # Métricas gerais
    n_all = len(closed_all)
    wins_all = [t for t in closed_all if t["result"] == "WIN"]
    wr_all = len(wins_all) / n_all * 100 if n_all else 0
    pnl_all = sum(float(t.get("pnl") or 0) for t in closed_all)
    retorno_pct = (balance - start_balance) / start_balance * 100

    # Métricas semana atual
    n_week = len(this_week)
    wins_week = [t for t in this_week if t["result"] == "WIN"]
    wr_week = len(wins_week) / n_week * 100 if n_week else 0
    pnl_week = sum(float(t.get("pnl") or 0) for t in this_week)

    # Métricas semana passada (para comparação)
    n_last = len(last_week)
    wins_last = [t for t in last_week if t["result"] == "WIN"]
    wr_last = len(wins_last) / n_last * 100 if n_last else 0
    pnl_last = sum(float(t.get("pnl") or 0) for t in last_week)

    brier_week = _brier(this_week)
    brier_last = _brier(last_week)
    sharpe_week = _sharpe(this_week)
    pf_week = _profit_factor(this_week)

    # Tendência de calibração
    if brier_week is not None and brier_last is not None:
        cal_trend = "📉 melhorou" if brier_week < brier_last else "📈 piorou"
        cal_str = f"{brier_week:.4f} ({cal_trend} vs {brier_last:.4f})"
    elif brier_week is not None:
        cal_str = f"{brier_week:.4f}"
    else:
        cal_str = "N/A (sem model_prob nos trades)"

    now_str = datetime.now(timezone.utc).strftime("%d/%m/%Y")
    emoji_semana = "🟢" if pnl_week >= 0 else "🔴"
    emoji_geral = "🟢" if pnl_all >= 0 else "🔴"

    relatorio = (
        f"<b>📊 RELATÓRIO SEMANAL — {now_str}</b>\n"
        f"{'─'*32}\n\n"

        f"<b>Esta semana</b>\n"
        f"{emoji_semana} PnL: <b>${pnl_week:+.2f}</b>\n"
        f"Trades: {n_week} | {len(wins_week)}W/{n_week-len(wins_week)}L | WR: <b>{wr_week:.1f}%</b>\n"
        f"Semana passada: {n_last} trades | WR: {wr_last:.1f}% | PnL: ${pnl_last:+.2f}\n\n"

        f"<b>Modelo</b>\n"
        f"Brier score: <b>{cal_str}</b>\n"
        f"Sharpe: {sharpe_week:.3f}\n" if sharpe_week else ""
        f"Profit Factor: {pf_week:.2f}x\n\n" if pf_week else ""

        f"<b>Histórico completo</b>\n"
        f"{emoji_geral} PnL total: <b>${pnl_all:+.2f}</b> ({retorno_pct:+.1f}%)\n"
        f"Saldo: <b>${balance:.2f}</b> | Abertos: {len(open_trades)}\n"
        f"Total: {n_all} trades | WR: {wr_all:.1f}%\n\n"

        f"<b>Calibração do modelo</b>\n"
        f"{_calibration_text(closed_all[-30:])}\n\n"

        f"<b>Top cidades (todas)</b>\n"
        f"{_by_city(closed_all)}\n\n"

        f"<b>Por tipo de aposta</b>\n"
        f"{_by_type(closed_all)}\n\n"
    )

    # Veredito
    if n_all < 30:
        veredito = f"⏳ Amostra pequena ({n_all}/30 mínimo) — aguardando mais dados"
    elif wr_all >= 60 and pnl_all > 0:
        veredito = "✅ Modelo com edge positivo — continuar operando"
    elif wr_all >= 50 and pnl_all > 0:
        veredito = "🟡 Edge marginal — monitorar por mais 2 semanas"
    else:
        veredito = "🔴 Sem edge claro — revisar parâmetros"

    relatorio += f"<b>Veredito:</b> {veredito}"

    if enviar_telegram:
        try:
            from notificador import enviar_mensagem
            enviar_mensagem(relatorio)
            print(f"Relatório semanal enviado ({n_week} trades esta semana)")
        except Exception as e:
            print(f"Telegram erro: {e}")

    return relatorio


if __name__ == "__main__":
    print(gerar_relatorio_semanal(enviar_telegram=False))
