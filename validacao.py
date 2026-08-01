"""
validacao.py — Validação do modelo lendo direto do bankroll.

Não depende de validacao.json — usa bankroll como fonte única da verdade.

Funções exportadas:
    registrar_resultado(market_id, result, real_temp_c, pnl)  — no-op, mantido por compatibilidade
    gerar_relatorio(enviar_telegram=False)

CORREÇÕES (auditoria):
1. Intervalo de confiança do win rate agora é o Wilson score interval.
   O método antigo (binom.ppf com p_hat plug-in) é estatisticamente
   inválido para inferência sobre p: com n=5 e 5 vitórias devolvia
   CI [100%, 100%] — certeza absoluta com 5 amostras — e aprovava o
   modelo. Wilson com n=5, wins=5 dá [~57%, 100%], que é o correto.
2. Brier score e edge realizado agora são CIENTES DO LADO do trade.
   model_prob é sempre a prob de YES; para um trade NO, a probabilidade
   apostada é (1 − model_prob). Comparar model_prob com WIN do trade NO
   invertia o sinal das duas métricas — com 18 dos 28 trades reais sendo
   NO, as métricas agregadas eram lixo.

CORREÇÃO 2026-08-01 (pós-auditoria de fonte de dados):
3. O histórico anterior a este corte está contaminado: Los Angeles (39%
   dos trades fechados) foi liquidado com uma coordenada que divergia em
   +12.3°F em média da temperatura implícita nos preços do mercado.
   gerar_relatorio() agora conta APENAS trades abertos a partir de
   VALIDATION_CUTOFF_ISO (deploy do fix, PR #9, confirmado nos logs do
   Render) para decidir o veredito. O histórico completo continua
   disponível via `incluir_pre_corte=True`, mas nunca conta pra aprovação.
4. Critérios de aprovação alinhados ao README: min N_MIN_VALIDACAO=110
   trades (era 20, arbitrário), CI95% inferior >= CI_LOWER_MIN=0.52 (era
   0.50 — o README sempre exigiu 52%, o código usava um número diferente
   do que o projeto documentava), e MIN_RANGE2_TRADES=10 fechados desse
   tipo (README: "pelo menos 10 trades RANGE2 para calibrar sigma").
"""

from datetime import timezone, datetime

# Deploy do PR #9 (fix/auditoria-2026-08), confirmado no log do Render:
# "2026-08-01 19:32:49 [INFO] bot: Weather Quant Bot | 19 cidades ativas".
# Trades com entry_time anterior a isto foram decididos pelo código antigo
# (coordenada de LA errada, ML sem trava, sigma que nunca convergia) e não
# contam para a validação de ir a capital real.
VALIDATION_CUTOFF_ISO = "2026-08-01T19:30:00+00:00"

N_MIN_VALIDACAO   = 110    # README: mínimo de trades fechados
CI_LOWER_MIN      = 0.52   # README: IC 95% inferior do win rate
MIN_RANGE2_TRADES = 10     # README: trades RANGE2 fechados para calibrar sigma
BRIER_MAX         = 0.25


def _pos_corte(trade, cutoff_iso=VALIDATION_CUTOFF_ISO) -> bool:
    """True se o trade foi ABERTO depois do corte de validação."""
    raw = trade.get("entry_time") or ""
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        cutoff = datetime.fromisoformat(cutoff_iso)
        return dt >= cutoff
    except Exception:
        # Sem entry_time parseável (trades muito antigos, pré-schema
        # atual): tratado como pré-corte — não conta para validação.
        return False


# ── Compatibilidade — settlement ainda chama isso ────────────────────────────

def registrar_resultado(market_id, result, real_temp_c, pnl):
    """No-op — dados ficam no bankroll, não precisamos de arquivo separado."""
    pass


# ── Probabilidade apostada (ciente do lado) ──────────────────────────────────

def prob_apostada(trade) -> float:
    """
    Probabilidade que o BOT atribuiu ao desfecho em que apostou:
      YES → model_prob ;  NO → 1 − model_prob.
    model_prob é sempre a probabilidade de o mercado resolver YES.
    """
    p = float(trade.get("model_prob") or 0.5)
    side = str(trade.get("side", "YES")).upper()
    return (1.0 - p) if side == "NO" else p


# ── Intervalo de confiança binomial (Wilson score) ───────────────────────────

def _confianca_binomial(n, wins, confidence=0.95):
    """
    Wilson score interval para a proporção de vitórias.
    Correto para n pequeno (não colapsa para [1,1] com 5/5) e não
    depende de plug-in de p_hat na distribuição.
    """
    if n < 1:
        return None, None

    # z para o nível de confiança (0.95 → 1.959964)
    try:
        from scipy.stats import norm
        z = float(norm.ppf(1 - (1 - confidence) / 2))
    except ImportError:
        z = 1.96  # 95%

    p_hat = wins / n
    z2 = z * z
    denom  = 1 + z2 / n
    center = (p_hat + z2 / (2 * n)) / denom
    margin = (z / denom) * ((p_hat * (1 - p_hat) / n + z2 / (4 * n * n)) ** 0.5)

    ci_lower = max(0.0, center - margin)
    ci_upper = min(1.0, center + margin)
    return round(ci_lower, 4), round(ci_upper, 4)


# ── Veredito ─────────────────────────────────────────────────────────────────

def _veredito(n, wins, brier, edge_realizado_pct, n_range2=None):
    if n < 5:
        return "AGUARDANDO", (
            f"Apenas {n} trades pós-correção resolvidos de {N_MIN_VALIDACAO} — "
            f"mínimo 5 só para diagnóstico inicial, nada aprovável ainda"
        )

    status = "DADOS INSUFICIENTES" if n < N_MIN_VALIDACAO else "CONFIÁVEL"
    msg    = (
        f"{n}/{N_MIN_VALIDACAO} trades pós-correção — veredito provisório"
        if n < N_MIN_VALIDACAO else f"{n} trades pós-correção — estatística robusta"
    )

    ci_lower, ci_upper = _confianca_binomial(n, wins)

    aprovado = (
        n >= N_MIN_VALIDACAO
        and ci_lower is not None and ci_lower >= CI_LOWER_MIN
        and brier is not None and brier < BRIER_MAX
        and edge_realizado_pct is not None and edge_realizado_pct > 0
        and (n_range2 is None or n_range2 >= MIN_RANGE2_TRADES)
    )

    ci_str = f"CI 95%: [{ci_lower*100:.1f}%, {ci_upper*100:.1f}%]" if ci_lower is not None else ""

    if aprovado:
        return f"APROVADO ({status})", f"{msg} — {ci_str}"

    razoes = []
    if n < N_MIN_VALIDACAO:
        razoes.append(f"n={n} < {N_MIN_VALIDACAO}")
    if ci_lower is None or ci_lower < CI_LOWER_MIN:
        razoes.append(f"WR {ci_str} < {CI_LOWER_MIN*100:.0f}%")
    if brier is not None and brier >= BRIER_MAX:
        razoes.append(f"Brier {brier:.4f} ≥ {BRIER_MAX}")
    if edge_realizado_pct is not None and edge_realizado_pct <= 0:
        razoes.append(f"Edge realizado {edge_realizado_pct:+.1f}% ≤ 0")
    if n_range2 is not None and n_range2 < MIN_RANGE2_TRADES:
        razoes.append(f"RANGE2: {n_range2} < {MIN_RANGE2_TRADES}")

    return f"REPROVADO ({status})", " | ".join(razoes) if razoes else msg


# ── Relatório ─────────────────────────────────────────────────────────────────

def gerar_relatorio(enviar_telegram=False):
    from bankroll import load_bankroll

    history_completo = load_bankroll().get("history", [])
    history  = [t for t in history_completo if _pos_corte(t)]
    n_pre_corte = len(history_completo) - len(history)

    fechados = [t for t in history if t.get("result") in ("WIN", "LOSS")]
    abertos  = [t for t in history if t.get("result") == "OPEN"]
    wins     = [t for t in fechados if t.get("result") == "WIN"]
    losses   = [t for t in fechados if t.get("result") == "LOSS"]
    n_range2 = sum(1 for t in fechados if str(t.get("type", "")).upper() == "RANGE2")

    n        = len(fechados)
    win_rate = len(wins) / n if n > 0 else 0
    pnl_total = sum(t.get("pnl") or 0 for t in fechados)

    # Brier score — usa a probabilidade DO LADO APOSTADO vs o resultado
    # do trade (WIN/LOSS). Para NO: prob apostada = 1 − model_prob.
    brier = None
    brier_vals = [
        (prob_apostada(t) - (1.0 if t.get("result") == "WIN" else 0.0)) ** 2
        for t in fechados if t.get("model_prob") is not None
    ]
    if brier_vals:
        brier = round(sum(brier_vals) / len(brier_vals), 4)

    # Edge realizado: média(outcome - prob_apostada), positivo = modelo
    # subestimou a chance do lado apostado.
    edge_realizado_pct = None
    edge_vals = [
        (1.0 if t.get("result") == "WIN" else 0.0) - prob_apostada(t)
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

    veredito, detalhe = _veredito(n, len(wins), brier, edge_realizado_pct, n_range2)

    emoji_pnl   = "🟢" if pnl_total >= 0 else "🔴"
    emoji_brier = "✅" if brier is not None and brier < BRIER_MAX else "⚠️"
    emoji_edge  = "✅" if edge_realizado_pct is not None and edge_realizado_pct > 0 else "⚠️"

    relatorio = (
        f"<b>📊 VALIDAÇÃO PÓS-CORREÇÃO (desde {VALIDATION_CUTOFF_ISO[:10]})</b>\n\n"
        f"Fechados: <b>{n}</b>/{N_MIN_VALIDACAO} ({len(wins)}W / {len(losses)}L) | "
        f"Abertos: {len(abertos)} | RANGE2 fechados: {n_range2}/{MIN_RANGE2_TRADES}\n"
        f"Win rate: <b>{win_rate*100:.1f}%</b>\n"
        f"{emoji_pnl} PnL: <b>${pnl_total:+.2f}</b>\n\n"
        f"Brier score: <b>{brier:.4f}</b> {emoji_brier}\n"
        f"Edge realizado: <b>{edge_realizado_pct:+.1f}%</b> {emoji_edge}\n"
        if brier is not None and edge_realizado_pct is not None else
        f"<b>📊 VALIDAÇÃO PÓS-CORREÇÃO (desde {VALIDATION_CUTOFF_ISO[:10]})</b>\n\n"
        f"Fechados: <b>{n}</b>/{N_MIN_VALIDACAO} ({len(wins)}W / {len(losses)}L) | "
        f"Abertos: {len(abertos)} | RANGE2 fechados: {n_range2}/{MIN_RANGE2_TRADES}\n"
        f"Win rate: <b>{win_rate*100:.1f}%</b>\n"
        f"{emoji_pnl} PnL: <b>${pnl_total:+.2f}</b>\n\n"
        f"Brier: N/A | Edge realizado: N/A\n"
    )

    if tipo_lines:
        relatorio += f"\n<b>Por tipo:</b>{tipo_lines}\n"

    if cidade_lines:
        relatorio += f"\n<b>Top cidades:</b>{cidade_lines}\n"

    relatorio += f"\n<b>Veredito: {veredito}</b>\n<i>{detalhe}</i>"

    if n_pre_corte:
        relatorio += (
            f"\n\n<i>({n_pre_corte} trades anteriores ao fix de fonte de dados "
            f"(coordenada de Los Angeles) excluídos — não contam para este veredito.)</i>"
        )

    if enviar_telegram:
        try:
            from notificador import enviar_mensagem
            enviar_mensagem(relatorio)
        except Exception as e:
            print(f"[validacao] Telegram erro: {e}")

    return relatorio


if __name__ == "__main__":
    print(gerar_relatorio(enviar_telegram=False))
