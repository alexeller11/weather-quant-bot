"""
SISTEMA DE VALIDAÇÃO — WEATHER QUANT
=====================================
Roda paralelo ao bot em papel (paper trading).
Registra previsões do modelo vs resultado real e calcula métricas de confiança.

Uso:
    python validacao.py          ← relatório atual
    python validacao.py reset    ← zera histórico de validação

O bot chama registrar_previsao() automaticamente a cada ciclo.
O settlement chama registrar_resultado() após resolução.
"""

import os, json, math
from datetime import datetime, timezone

VALIDACAO_FILE = "validacao.json"

# ─────────────────────────────────────────────────────────────
# PERSISTÊNCIA
# ─────────────────────────────────────────────────────────────

def _load():
    if os.path.exists(VALIDACAO_FILE):
        with open(VALIDACAO_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"previsoes": []}

def _save(data):
    with open(VALIDACAO_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    # Auto-commit no GitHub se configurado
    try:
        from github_sync import commit_validacao
        commit_validacao(data)
    except Exception:
        pass

# ─────────────────────────────────────────────────────────────
# REGISTRO
# ─────────────────────────────────────────────────────────────

def registrar_previsao(market_id, city, market_date, target, unit,
                        condition, model_prob, market_price, forecast_mean_c, sigma_c,
                        edge, ev, stake, real_cost, shares):
    """
    Registra previsão no momento da entrada do trade.
    Chamado pelo bot.py ao entrar em cada trade.
    """
    data = _load()
    ts   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Evita duplicata
    ids = [p["market_id"] for p in data["previsoes"]]
    if market_id in ids:
        return

    data["previsoes"].append({
        "market_id":     market_id,
        "city":          city,
        "market_date":   market_date,
        "target":        target,
        "unit":          unit,
        "condition":     condition,
        "model_prob":    model_prob,
        "market_price":  market_price,
        "forecast_mean_c": forecast_mean_c,
        "sigma_c":       sigma_c,
        "edge":          edge,
        "ev":            ev,
        "stake":         stake,
        "real_cost":     real_cost,
        "shares":        shares,
        "registered_at": ts,
        # preenchidos no settlement
        "result":        None,
        "real_temp_c":   None,
        "pnl":           None,
        "resolved_at":   None,
    })
    _save(data)


def registrar_resultado(market_id, result, real_temp_c, pnl):
    """
    Registra resultado real após settlement.
    Chamado pelo settlement.py.
    """
    data = _load()
    for p in data["previsoes"]:
        if p["market_id"] == market_id and p["result"] is None:
            p["result"]      = result  # "WIN" ou "LOSS"
            p["real_temp_c"] = real_temp_c
            p["pnl"]         = pnl
            p["resolved_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            break
    _save(data)

# ─────────────────────────────────────────────────────────────
# MÉTRICAS
# ─────────────────────────────────────────────────────────────

def _brier_score(previsoes_resolvidas):
    """Brier Score médio. Quanto menor melhor (0 = perfeito)."""
    if not previsoes_resolvidas:
        return None
    total = 0.0
    for p in previsoes_resolvidas:
        outcome = 1.0 if p["result"] == "WIN" else 0.0
        total  += (p["model_prob"] - outcome) ** 2
    return round(total / len(previsoes_resolvidas), 4)

def _log_loss(previsoes_resolvidas):
    """Log Loss médio. Penaliza previsões confiantes e erradas."""
    if not previsoes_resolvidas:
        return None
    total = 0.0
    for p in previsoes_resolvidas:
        outcome = 1.0 if p["result"] == "WIN" else 0.0
        prob    = max(min(p["model_prob"], 0.9999), 0.0001)
        total  -= outcome * math.log(prob) + (1 - outcome) * math.log(1 - prob)
    return round(total / len(previsoes_resolvidas), 4)

def _calibracao(previsoes_resolvidas, n_buckets=5):
    """
    Calibração do modelo: agrupa por faixas de probabilidade
    e compara prob prevista vs freq observada.
    Retorna lista de buckets com (prob_media, freq_real, n).
    """
    if not previsoes_resolvidas:
        return []
    buckets = [[] for _ in range(n_buckets)]
    for p in previsoes_resolvidas:
        idx = min(int(p["model_prob"] * n_buckets), n_buckets - 1)
        buckets[idx].append(p)
    resultado = []
    for i, bucket in enumerate(buckets):
        if not bucket:
            continue
        prob_media = sum(p["model_prob"] for p in bucket) / len(bucket)
        freq_real  = sum(1 for p in bucket if p["result"] == "WIN") / len(bucket)
        resultado.append({
            "faixa":      f"{i*100//n_buckets}–{(i+1)*100//n_buckets}%",
            "prob_media": round(prob_media * 100, 1),
            "freq_real":  round(freq_real * 100, 1),
            "n":          len(bucket),
            "ok":         abs(prob_media - freq_real) < 0.10,
        })
    return resultado

def _edge_realizado(previsoes_resolvidas):
    """
    Edge realizado vs edge esperado.
    Edge esperado = model_prob - market_price
    Edge realizado = win_rate - market_price_media
    """
    if not previsoes_resolvidas:
        return None, None
    edge_esp   = sum(p["edge"] for p in previsoes_resolvidas) / len(previsoes_resolvidas)
    win_rate   = sum(1 for p in previsoes_resolvidas if p["result"] == "WIN") / len(previsoes_resolvidas)
    mkt_media  = sum(p["market_price"] for p in previsoes_resolvidas) / len(previsoes_resolvidas)
    edge_real  = win_rate - mkt_media
    return round(edge_esp * 100, 1), round(edge_real * 100, 1)

def _veredito(n, win_rate, brier, edge_real_pct):
    """
    Retorna veredito final com base em n amostras.
    Precisa de mínimo 20 trades resolvidos para ser confiável.
    """
    if n < 5:
        return "AGUARDANDO", f"Apenas {n} trades resolvidos — mínimo 5 para diagnóstico inicial"
    if n < 20:
        status = "DADOS INSUFICIENTES"
        msg    = f"{n}/20 trades resolvidos — veredito provisório"
    else:
        status = "CONFIÁVEL"
        msg    = f"{n} trades resolvidos — estatística robusta"

    # Critérios de aprovação
    aprovado = (
        win_rate >= 0.55 and
        brier is not None and brier < 0.25 and
        edge_real_pct is not None and edge_real_pct > 0
    )

    if aprovado:
        return f"APROVADO ({status})", msg
    else:
        razoes = []
        if win_rate < 0.55:
            razoes.append(f"win rate {win_rate*100:.1f}% < 55%")
        if brier and brier >= 0.25:
            razoes.append(f"Brier {brier} ≥ 0.25")
        if edge_real_pct is not None and edge_real_pct <= 0:
            razoes.append(f"edge realizado {edge_real_pct}% ≤ 0")
        return f"REPROVADO ({status})", " | ".join(razoes)

# ─────────────────────────────────────────────────────────────
# RELATÓRIO
# ─────────────────────────────────────────────────────────────

def gerar_relatorio(enviar_telegram=False):
    """
    Gera relatório completo de validação.
    Se enviar_telegram=True, manda pelo Telegram também.
    """
    data      = _load()
    todas     = data["previsoes"]
    resolvidas = [p for p in todas if p["result"] in ("WIN", "LOSS")]
    abertas    = [p for p in todas if p["result"] is None]
    wins       = [p for p in resolvidas if p["result"] == "WIN"]

    n       = len(resolvidas)
    win_rate = len(wins) / n if n > 0 else 0
    pnl_total = sum(p.get("pnl", 0) or 0 for p in resolvidas)
    brier    = _brier_score(resolvidas)
    ll       = _log_loss(resolvidas)
    cal      = _calibracao(resolvidas)
    edge_esp, edge_real = _edge_realizado(resolvidas)
    veredito, razao     = _veredito(n, win_rate, brier, edge_real)

    # ── Texto do relatório ──────────────────────────────────────

    linhas = [
        "=" * 52,
        "  RELATÓRIO DE VALIDAÇÃO — WEATHER QUANT",
        f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "=" * 52,
        "",
        f"  Trades registrados : {len(todas)}",
        f"  Resolvidos         : {n}",
        f"  Em aberto          : {len(abertas)}",
        "",
        "── PERFORMANCE ─────────────────────────────────────",
        f"  Win rate           : {win_rate*100:.1f}% ({len(wins)}W/{n-len(wins)}L)",
        f"  PnL total          : ${pnl_total:+.2f}",
        f"  Edge esperado      : {edge_esp}%" if edge_esp is not None else "  Edge esperado      : —",
        f"  Edge realizado     : {edge_real}%" if edge_real is not None else "  Edge realizado     : —",
        "",
        "── QUALIDADE DO MODELO ──────────────────────────────",
        f"  Brier Score        : {brier}  (< 0.20 = ótimo, < 0.25 = bom)",
        f"  Log Loss           : {ll}",
        "",
    ]

    if cal:
        linhas.append("── CALIBRAÇÃO ───────────────────────────────────────")
        linhas.append(f"  {'Faixa':<10} {'Previsto':>10} {'Realizado':>10} {'N':>5}  {'OK?':>5}")
        for b in cal:
            ok_str = "✓" if b["ok"] else "✗"
            linhas.append(
                f"  {b['faixa']:<10} {b['prob_media']:>9.1f}% {b['freq_real']:>9.1f}% {b['n']:>5}  {ok_str:>5}"
            )
        linhas.append("")

    linhas += [
        "── VEREDITO ─────────────────────────────────────────",
        f"  {veredito}",
        f"  {razao}",
        "",
        "── CRITÉRIOS PARA DINHEIRO REAL ─────────────────────",
        f"  Win rate ≥ 55%     : {'✓' if win_rate >= 0.55 else '✗'}  ({win_rate*100:.1f}%)",
        f"  Brier < 0.25       : {'✓' if brier and brier < 0.25 else '✗'}  ({brier})",
        f"  Edge realizado > 0 : {'✓' if edge_real and edge_real > 0 else '✗'}  ({edge_real}%)",
        f"  Mínimo 20 trades   : {'✓' if n >= 20 else '✗'}  ({n}/20)",
        "=" * 52,
    ]

    texto = "\n".join(linhas)
    print(texto)

    # ── Telegram ────────────────────────────────────────────────
    if enviar_telegram:
        try:
            from notificador import enviar_mensagem
            emoji_verd = "✅" if "APROVADO" in veredito else ("⏳" if "AGUARDANDO" in veredito else "❌")
            msg = (
                f"<b>{emoji_verd} VALIDAÇÃO DO MODELO</b>\n\n"
                f"<b>Trades resolvidos:</b> {n}\n"
                f"<b>Win rate:</b> <b>{win_rate*100:.1f}%</b>\n"
                f"<b>PnL total:</b> ${pnl_total:+.2f}\n"
                f"<b>Brier Score:</b> {brier}\n"
                f"<b>Edge esperado:</b> {edge_esp}%\n"
                f"<b>Edge realizado:</b> {edge_real}%\n\n"
                f"<b>Critérios p/ dinheiro real:</b>\n"
                f"{'✅' if win_rate >= 0.55 else '❌'} Win rate ≥ 55% ({win_rate*100:.1f}%)\n"
                f"{'✅' if brier and brier < 0.25 else '❌'} Brier &lt; 0.25 ({brier})\n"
                f"{'✅' if edge_real and edge_real > 0 else '❌'} Edge realizado &gt; 0 ({edge_real}%)\n"
                f"{'✅' if n >= 20 else '❌'} Mínimo 20 trades ({n}/20)\n\n"
                f"<b>Veredito:</b> {veredito}\n"
                f"<i>{razao}</i>"
            )
            enviar_mensagem(msg)
        except Exception as e:
            print(f"Telegram erro: {e}")

    return {
        "n": n, "win_rate": win_rate, "pnl_total": pnl_total,
        "brier": brier, "log_loss": ll, "calibracao": cal,
        "edge_esperado": edge_esp, "edge_realizado": edge_real,
        "veredito": veredito, "razao": razao,
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "reset":
        _save({"previsoes": []})
        print("Histórico de validação zerado.")
    else:
        gerar_relatorio(enviar_telegram=False)
