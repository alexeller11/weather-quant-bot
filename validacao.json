"""
validacao.py — Validação do modelo lendo direto do bankroll.

Não depende de validacao.json — usa bankroll como fonte única da verdade.

Funções exportadas:
    registrar_resultado(market_id, result, real_temp_c, pnl)  — no-op, mantido por compatibilidade
    gerar_relatorio(enviar_telegram=False)
"""

from datetime import timezone, datetime


# ── Compatibilidade — settlement ainda chama isso ────────────────────────────

def registrar_resultado(market_id, result, real_temp_c, pnl):
    """No-op — dados ficam no bankroll, não precisamos de arquivo separado."""
    pass


# ── Intervalo de confiança binomial ──────────────────────────────────────────

def _confianca_binomial(n, wins, confidence=0.95):
    if n < 1:
        return None, None
    try:
        from scipy.stats import binom
        p_hat = wins / n
        alpha = 1 - confidence
        ci_lower = binom.ppf(alpha / 2, n, p_hat) / n
        ci_upper = binom.ppf(1 - alpha / 2, n, p_hat) / n
        return round(ci_lower, 4), round(ci_upper, 4)
    except ImportError:
        p = wins / n
        margin = 1.96 * (p * (1 - p) / n) ** 0.5
        return round(max(0, p - margin), 4), round(min(1, p + margin), 4)


# ── Veredito ─────────────────────────────────────────────────────────────────

def _veredito(n, wins, brier, edge_realizado_pct):
    if n < 5:
        return "AGUARDANDO", f"Apenas {n} trades resolvidos — mínimo 5 para diagnóstico inicial"

    status = "DADOS INSUFICIENTES" if n < 20 else "CONFIÁVEL"
    msg    = f"{n}/20 trades — veredito provisório" if n < 20 else f"{n} trades — estatística robusta"

    ci_lower, ci_upper = _confianca_binomial(n, wins)

    aprovado = (
        ci_lower is not None and ci_lower >= 0.50
        and brier is not None and brier < 0.25
        and edge_realizado_pct is not None and edge_realizado_pct > 0
    )

    ci_str = f"CI 95%: [{ci_lower*100:.1f}%, {ci_upper*100:.1f}%]" if ci_lower is not None else ""

    if aprovado:
        return f"APROVADO ({status})", f"{msg} — {ci_str}"

    razoes = []
    if ci_lower is None or ci_lower < 0.50:
        razoes.append(f"WR {ci_str} insuficiente")
    if brier is not None and brier >= 0.25:
        razoes.append(f"Brier {brier:.4f} ≥ 0.25")
    if edge_realizado_pct is not None and edge_realizado_pct <= 0:
        razoes.append(f"Edge realizado {edge_realizado_pct:+.1f}% ≤ 0")

    return f"REPROVADO ({status})", " | ".join(razoes) if razoes else msg


# ── Relatório ─────────────────────────────────────────────────────────────────

def gerar_relatorio(enviar_telegram=False):
    from bankroll import load_bankroll

    history  = load_bankroll().get("history", [])
    fechados = [t for t in history if t.get("result") in ("WIN", "LOSS")]
    abertos  = [t for t in history if t.get("result") == "OPEN"]
    wins     = [t for t in fechados if t.get("result") == "WIN"]
    losses   = [t for t in fechados if t.get("result") == "LOSS"]

    n        = len(fechados)
    win_rate = len(wins) / n if n > 0 else 0
    pnl_total = sum(t.get("pnl") or 0 for t in fechados)

    # Brier score
    brier = None
    brier_vals = [
        (t.get("model_prob", 0) - (1.0 if t.get("result") == "WIN" else 0.0)) ** 2
        for t in fechados if t.get("model_prob") is not None
    ]
    if brier_vals:
        brier = round(sum(brier_vals) / len(brier_vals), 4)

    # Edge realizado: média(outcome - model_prob), positivo = modelo subestimou
    edge_realizado_pct = None
    edge_vals = [
        (1.0 if t.get("result") == "WIN" else 0.0) - (t.get("model_prob") or 0)
        for t in fechados if t.get("model_prob") is not None
    ]
    if edge_vals:
        edge_realizado_pct = round(sum(edge_vals) / len(edge_vals) * 100, 2)

    # Breakdown por condição (type)
    por_tipo = {}
    for t in fechados:
        tipo = t.get("type", "?").upper()
        if tipo not in por_tipo:
            por_tipo[tipo] = {"wins": 0, "losses": 0, "pnl": 0.0}
        if t.get("result") == "WIN":
            por_tipo[tipo]["wins"] += 1
        else:
            por_tipo[tipo]["losses"] += 1
        por_tipo[tipo]["pnl"] += t.get("pnl") or 0

    tipo_lines = ""
    for tipo, s in sorted(por_tipo.items()):
        total_t = s["wins"] + s["losses"]
        wr_t    = s["wins"] / total_t * 100 if total_t else 0
        tipo_lines += f"\n  {tipo:6} {s['wins']}W/{s['losses']}L ({wr_t:.0f}%) PnL ${s['pnl']:+.2f}"

    # Breakdown por cidade (top 5 por volume)
    por_cidade = {}
    for t in fechados:
        city = t.get("city", "?")
        if city not in por_cidade:
            por_cidade[city] = {"wins": 0, "losses": 0, "pnl": 0.0}
        if t.get("result") == "WIN":
            por_cidade[city]["wins"] += 1
        else:
            por_cidade[city]["losses"] += 1
        por_cidade[city]["pnl"] += t.get("pnl") or 0

    top_cidades = sorted(por_cidade.items(), key=lambda x: -(x[1]["wins"] + x[1]["losses"]))[:5]
    cidade_lines = ""
    for city, s in top_cidades:
        total_c = s["wins"] + s["losses"]
        wr_c    = s["wins"] / total_c * 100 if total_c else 0
        cidade_lines += f"\n  {city:15} {s['wins']}W/{s['losses']}L ({wr_c:.0f}%) ${s['pnl']:+.2f}"

    veredito, detalhe = _veredito(n, len(wins), brier, edge_realizado_pct)

    emoji_pnl   = "🟢" if pnl_total >= 0 else "🔴"
    emoji_brier = "✅" if brier is not None and brier < 0.25 else "⚠️"
    emoji_edge  = "✅" if edge_realizado_pct is not None and edge_realizado_pct > 0 else "⚠️"

    relatorio = (
        f"<b>📊 VALIDAÇÃO DO MODELO</b>\n\n"
        f"Fechados: <b>{n}</b> ({len(wins)}W / {len(losses)}L) | Abertos: {len(abertos)}\n"
        f"Win rate: <b>{win_rate*100:.1f}%</b>\n"
        f"{emoji_pnl} PnL: <b>${pnl_total:+.2f}</b>\n\n"
        f"Brier score: <b>{brier:.4f}</b> {emoji_brier}\n"
        f"Edge realizado: <b>{edge_realizado_pct:+.1f}%</b> {emoji_edge}\n"
        if brier is not None and edge_realizado_pct is not None else
        f"<b>📊 VALIDAÇÃO DO MODELO</b>\n\n"
        f"Fechados: <b>{n}</b> ({len(wins)}W / {len(losses)}L) | Abertos: {len(abertos)}\n"
        f"Win rate: <b>{win_rate*100:.1f}%</b>\n"
        f"{emoji_pnl} PnL: <b>${pnl_total:+.2f}</b>\n\n"
        f"Brier: N/A | Edge realizado: N/A\n"
    )

    if tipo_lines:
        relatorio += f"\n<b>Por tipo:</b>{tipo_lines}\n"

    if cidade_lines:
        relatorio += f"\n<b>Top cidades:</b>{cidade_lines}\n"

    relatorio += f"\n<b>Veredito: {veredito}</b>\n<i>{detalhe}</i>"

    if enviar_telegram:
        try:
            from notificador import enviar_mensagem
            enviar_mensagem(relatorio)
        except Exception as e:
            print(f"[validacao] Telegram erro: {e}")

    return relatorio


if __name__ == "__main__":
    print(gerar_relatorio(enviar_telegram=False))
