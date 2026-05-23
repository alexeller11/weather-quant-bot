def _confianca_binomial(n, wins, confidence=0.95):
    """
    FIX #17: Calcula intervalo de confiança 95% para win rate.
    
    Retorna (ci_lower, ci_upper) da proporção de sucessos.
    """
    if n < 1:
        return None, None
    
    try:
        from scipy.stats import binom
    except ImportError:
        # Fallback simples se scipy não está disponível
        p = wins / n if n > 0 else 0
        margin = 1.96 * (p * (1-p) / n) ** 0.5 if n > 0 else 0
        return max(0, p - margin), min(1, p + margin)
    
    p_hat = wins / n if n > 0 else 0
    alpha = 1 - confidence
    
    ci_lower = binom.ppf(alpha/2, n, p_hat) / n if n > 0 else 0
    ci_upper = binom.ppf(1 - alpha/2, n, p_hat) / n if n > 0 else 1
    
    return ci_lower, ci_upper


def _veredito(n, win_rate, brier, edge_real_pct):
    """
    FIX #17: Veredito agora usa intervalo de confiança.
    """
    if n < 5:
        return "AGUARDANDO", f"Apenas {n} trades resolvidos — mínimo 5 para diagnóstico inicial"
    if n < 20:
        status = "DADOS INSUFICIENTES"
        msg    = f"{n}/20 trades resolvidos — veredito provisório"
    else:
        status = "CONFIÁVEL"
        msg    = f"{n} trades resolvidos — estatística robusta"

    # Calcular intervalo de confiança
    wins = int(win_rate * n)
    ci_lower, ci_upper = _confianca_binomial(n, wins, confidence=0.95)

    # Critérios de aprovação
    # Agora verifica se CI lower está acima de 55%
    aprovado = (
        ci_lower >= 0.50 and  # Pelo menos 95% confiante que WR > 50%
        brier is not None and brier < 0.25 and
        edge_real_pct is not None and edge_real_pct > 0
    )

    if aprovado:
        ci_str = f"CI 95%: [{ci_lower*100:.1f}%, {ci_upper*100:.1f}%]"
        return f"APROVADO ({status})", f"{msg} — {ci_str}"
    else:
        razoes = []
        if ci_lower < 0.50:
            razoes.append(f"CI 95% WR: [{ci_lower*100:.1f}%, {ci_upper*100:.1f}%] (não suficientemente > 50%)")
        if brier and brier >= 0.25:
            razoes.append(f"Brier {brier} ≥ 0.25")
        if edge_real_pct is not None and edge_real_pct <= 0:
            razoes.append(f"edge realizado {edge_real_pct}% ≤ 0")
        return f"REPROVADO ({status})", " | ".join(razoes)
