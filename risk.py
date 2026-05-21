from config import MAX_POSITION, KELLY_FRACTION

def kelly_stake(current_balance, model_prob, market_price):
    """
    Calcula aposta ótima via half-Kelly.

    Fórmula:
        b  = (1 / market_price) - 1     ← odds líquidas de vitória
        f* = (p*b - q) / b              ← fração Kelly pura
        fraction = min(f* * KELLY_FRACTION, MAX_POSITION)
        stake = current_balance * fraction

    Args:
        current_balance: bankroll atual já recarregado do disco
        model_prob:      probabilidade estimada pelo modelo (p)
        market_price:    preço YES do mercado

    Returns:
        float: valor em $ a apostar (0.0 se sem edge)
    """
    if market_price <= 0 or market_price >= 1:
        return 0.0
    if current_balance <= 0:
        return 0.0

    p = model_prob
    q = 1.0 - p
    b = (1.0 / market_price) - 1.0

    if b <= 0:
        return 0.0

    f_star = (p * b - q) / b

    if f_star <= 0:
        return 0.0

    fraction = min(f_star * KELLY_FRACTION, MAX_POSITION)
    return max(round(current_balance * fraction, 2), 0.0)


def expected_value(model_prob, market_price):
    """
    EV por unidade apostada: model_prob / market_price - 1
    Positivo quando há edge. Ex: 0.60/0.52 - 1 = +15.4%
    """
    if market_price <= 0:
        return 0.0
    return round(model_prob / market_price - 1.0, 4)


def open_exposure(history):
    """Soma dos stakes de trades com result == OPEN."""
    return sum(t.get("stake", 0.0) for t in history if t.get("result") == "OPEN")


def effective_balance_for_exposure(balance, history, max_total_exposure):
    """
    Retorna o saldo de referência a usar no cálculo do limite de exposição.

    Problema: se o saldo cair após posições serem abertas, o limite recalculado
    pode ficar abaixo da exposição existente, travando o bot indefinidamente.

    Solução: o saldo de referência é o maior entre:
      - saldo atual (caso normal)
      - saldo implícito nas posições abertas
        (= exposure_atual / MAX_TOTAL_EXPOSURE)

    Isso garante que posições já abertas nunca causem bloqueio imediato,
    mas novos trades ainda são limitados pelo saldo real.

    Args:
        balance:             saldo atual do bankroll
        history:             lista de trades do bankroll
        max_total_exposure:  fração máxima de exposição (ex: 0.15)

    Returns:
        float: saldo efetivo para calcular max_allowed
    """
    if max_total_exposure <= 0:
        return balance

    exposure = open_exposure(history)
    # Saldo mínimo necessário para que as posições abertas não violem o limite
    implied_balance = exposure / max_total_exposure if exposure > 0 else 0.0
    return max(balance, implied_balance)