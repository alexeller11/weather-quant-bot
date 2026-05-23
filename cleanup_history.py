def fix_target(trade):
    """
    Se target < 20 (parece dia do mês), tenta extrair o threshold real
    da question.

    FIX #12: Usar regex melhor para evitar pegar data.

    Ex: target=14.0, question="...be 27°C or higher on May 14?"
        → corrige target para 27.0
    """
    question = trade.get("question", "")
    unit     = trade.get("unit", "C")
    target   = trade.get("target")

    if target is None or float(target) >= 20:
        return trade, False

    # FIX #12: Preferir padrão "be <número><unidade>"
    match = re.search(
        r"be\s+(\d+(?:\.\d+)?)\s*°[CcFf]",
        question,
        re.IGNORECASE
    )
    
    if match:
        new_target = float(match.group(1))
        if unit == "C" and new_target > 55:
            unit = "F"
        if abs(new_target - float(target)) > 0.01:
            trade = dict(trade)
            print(f"  Target corrigido: {trade.get('city')} "
                  f"market_id={trade.get('market_id')} "
                  f"{target} → {new_target} [{unit}]")
            trade["target"] = new_target
            return trade, True
        return trade, False

    # Fallback: extração por range (menos confiável)
    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", question)]

    if unit == "F":
        candidates = [n for n in nums if 50 <= n <= 120]
    else:
        candidates = [n for n in nums if 15 <= n <= 50]

    if not candidates:
        return trade, False

    new_target = candidates[0]
    if abs(new_target - float(target)) < 0.01:
        return trade, False

    trade = dict(trade)
    print(f"  Target corrigido: {trade.get('city')} "
          f"market_id={trade.get('market_id')} "
          f"{target} → {new_target} [{unit}]")
    trade["target"] = new_target
    return trade, True
