"""
TESTE - Diagnosticar por que não entra em trades
"""

from datetime import datetime, timezone
from gamma_parser import fetch_markets
from model import calculate_probability
from config import CITY_SLUGS, EDGE_THRESHOLD

def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)

print("=" * 80)
print("🔍 TESTE DE DIAGNÓSTICO")
print("=" * 80)
print(f"Data/Hora: {utcnow()}")
print(f"Edge mínimo: {EDGE_THRESHOLD * 100:.1f}%")
print()

for city in CITY_SLUGS[:2]:  # Testar apenas 2 primeiras
    print(f"\n📍 {city.upper()}")
    print("-" * 80)
    
    # Buscar mercados
    markets = fetch_markets(city)
    print(f"Mercados encontrados: {len(markets)}")
    
    if not markets:
        print("❌ PROBLEMA: Nenhum mercado encontrado!")
        print("   Possível causa: API Polymarket fora do ar")
        continue
    
    # Mostrar alguns
    for i, market in enumerate(markets[:3]):
        print(f"\n  Mercado #{i+1}:")
        print(f"    ID: {market.get('market_id')}")
        print(f"    Data: {market.get('market_date')}")
        print(f"    Pergunta: {market.get('question')[:60]}...")
        print(f"    Preço: {market.get('price'):.4f}")
        
        # Tentar calcular probabilidade
        market_date = market.get("market_date")
        question = market.get("question")
        
        cond_output = calculate_probability(city, market_date, question)
        
        if cond_output is None:
            print(f"    ❌ Não conseguiu calcular probabilidade")
            continue
        
        condition, unit, target, model_prob = cond_output
        market_price = market.get("price")
        
        edge = (model_prob / market_price - 1) if market_price > 0 else 0
        
        print(f"    Probabilidade modelo: {model_prob*100:.1f}%")
        print(f"    Edge: {edge*100:.1f}%")
        
        if edge >= EDGE_THRESHOLD:
            print(f"    ✅ BOM TRADE! (edge > {EDGE_THRESHOLD*100:.1f}%)")
        else:
            print(f"    ❌ Edge baixo (< {EDGE_THRESHOLD*100:.1f}%)")

print("\n" + "=" * 80)
print("DIAGNÓSTICO COMPLETO")
print("=" * 80)
print("""
Se viu:
✅ Muitos mercados → Edge muito baixo
   Solução: Reduzir EDGE_THRESHOLD em config.py (ex: 0.05)

❌ Nenhum mercado → API Polymarket fora
   Solução: Esperar e tentar depois

✅ Bons trades mostrados → Bot deve entrar no próximo ciclo
   Solução: Deixar rodar mais tempo
""")
