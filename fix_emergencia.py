"""
fix_emergencia.py
=================
Fecha os trades presos como OPEN para datas que já passaram.
Execute UMA VEZ para limpar o estado corrompido.

Uso no Railway Shell:
    python fix_emergencia.py
"""

from datetime import datetime
from bankroll import load_bankroll, save_bankroll

def utcnow():
    return datetime.utcnow()

print("=" * 50)
print("FIX DE EMERGÊNCIA — Fechando trades presos")
print("=" * 50)

data = load_bankroll()
history = data.get("history", [])
today = utcnow().date()

print(f"\nSaldo atual: ${data['balance']:.2f}")
print(f"Total trades: {len(history)}")

abertos = [t for t in history if t.get("result") == "OPEN"]
print(f"Trades OPEN: {len(abertos)}")

fechados_agora = 0

for trade in abertos:
    market_date_str = trade.get("market_date", "")
    city = trade.get("city", "?")
    stake = float(trade.get("stake", 0))
    market_id = trade.get("market_id", "?")

    try:
        trade_date = datetime.strptime(market_date_str, "%Y-%m-%d").date()
    except Exception:
        print(f"  IGNORADO (data inválida): {city} {market_date_str}")
        continue

    # Só fecha trades com data PASSADA (não futuros)
    if trade_date < today:
        trade["result"]    = "LOSS"
        trade["pnl"]       = round(-stake, 2)
        trade["fee"]       = 0.0
        trade["exit_time"] = utcnow().isoformat()
        print(f"  Fechando LOSS: {city:15} {market_date_str}  stake=${stake:.2f}  ID={market_id}")
        fechados_agora += 1
    else:
        print(f"  Mantendo OPEN: {city:15} {market_date_str}  (data futura)")

print(f"\nTrades fechados: {fechados_agora}")

if fechados_agora > 0:
    save_bankroll(data)
    print(f"Saldo após fix: ${data['balance']:.2f}")
    print("\n✅ Salvo com sucesso!")
    print("Agora substitua bankroll.py e settlement.py pelos novos arquivos.")
else:
    print("\nNenhum trade para fechar.")

print("=" * 50)
