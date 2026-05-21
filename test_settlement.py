#!/usr/bin/env python3
"""
TEST_SETTLEMENT.PY — Testa settlement com output detalhado
USO: python test_settlement.py
"""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)

print("\n" + "="*60)
print("🔍 TESTE RÁPIDO DE SETTLEMENT")
print("="*60)

# ══════════════════════════════════════════════════════════════
# DIAGNÓSTICO 1: Horários
# ══════════════════════════════════════════════════════════════

now_utc = utcnow()
now_brt = datetime.now()  # Local
today_utc = now_utc.date()
today_brt = now_brt.date()

print(f"\n⏰ HORÁRIOS AGORA:")
print(f"   UTC:      {now_utc.isoformat()}")
print(f"   Brasília: {now_brt.isoformat()}")
print(f"   Data UTC:      {today_utc}")
print(f"   Data Brasília: {today_brt}")

# ══════════════════════════════════════════════════════════════
# DIAGNÓSTICO 2: Arquivo bankroll.json
# ══════════════════════════════════════════════════════════════

bankroll_file = Path("bankroll.json")

print(f"\n📄 ARQUIVO BANKROLL.JSON:")
if not bankroll_file.exists():
    print(f"   ❌ NÃO ENCONTRADO em {bankroll_file.absolute()}")
else:
    with open(bankroll_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    print(f"   ✅ ENCONTRADO: {bankroll_file.absolute()}")
    print(f"   Balance: ${data.get('balance', 0):.2f}")
    
    history = data.get("history", [])
    print(f"   Total trades: {len(history)}")
    
    open_trades = [t for t in history if t.get("result") == "OPEN"]
    print(f"   Trades OPEN: {len(open_trades)}")
    
    # ════════════════════════════════════════════════════════════════
    # DIAGNÓSTICO 3: Analisar trades OPEN que deveriam resolver
    # ════════════════════════════════════════════════════════════════
    
    print(f"\n🔎 ANÁLISE DE TRADES OPEN (deveriam ser resolvidos):\n")
    
    resolvivel = 0
    futuro = 0
    incompleto = 0
    
    for i, trade in enumerate(open_trades):
        market_id = trade.get("market_id", f"trade_{i}")
        city = trade.get("city", "?")
        market_date_str = trade.get("market_date", "?")
        trade_type = trade.get("type", "?")
        target = trade.get("target", "?")
        
        print(f"   Trade #{i+1}: {city.upper():15} | ID: {market_id}")
        print(f"      Market date: {market_date_str}")
        
        # Validar se tem dados completos
        if not all([city, market_date_str, trade.get("target") is not None]):
            print(f"      ⚠️  INCOMPLETO (faltam dados)")
            incompleto += 1
            print()
            continue
        
        try:
            market_date = datetime.strptime(market_date_str, "%Y-%m-%d").date()
            
            if market_date > today_utc:
                dias_faltando = (market_date - today_utc).days
                print(f"      ⏳ FUTURO ({dias_faltando} dias faltando)")
                futuro += 1
            else:
                dias_atras = (today_utc - market_date).days
                print(f"      ✅ PRONTO PARA RESOLVER ({dias_atras} dias atrás)")
                print(f"         Tipo: {trade_type} {target}°")
                print(f"         Stake: ${trade.get('stake', 0):.2f}")
                print(f"         Market price: {trade.get('market_price', 0):.3f}")
                resolvivel += 1
        except Exception as e:
            print(f"      ❌ ERRO ao processar data: {e}")
            incompleto += 1
        
        print()
    
    # ════════════════════════════════════════════════════════════════
    # RESUMO
    # ════════════════════════════════════════════════════════════════
    
    print("="*60)
    print("📊 RESUMO:")
    print("="*60)
    print(f"   Trades OPEN resolúveis AGORA:  {resolvivel} ✅")
    print(f"   Trades OPEN (futuro):          {futuro} ⏳")
    print(f"   Trades OPEN (incompletos):     {incompleto} ⚠️")
    print(f"   Total OPEN:                    {len(open_trades)}")
    
    if resolvivel > 0:
        print(f"\n   🚀 Execute agora: python settlement.py")
        print(f"      Isso deve resolver {resolvivel} trade(s)")
    elif futuro > 0:
        print(f"\n   ⏳ Aguarde até amanhã (UTC) para resolver")
    else:
        print(f"\n   ℹ️  Nenhum trade pronto para resolver neste momento")
    
    print()

print("="*60)
print("✅ FIM DO TESTE")
print("="*60 + "\n")
