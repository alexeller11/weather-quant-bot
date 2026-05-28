"""
teste.py - Diagnostico de por que nao entra em trades.

CORRIGIDO: calculate_probability() tem assinatura:
    calculate_probability(city, target_temp, forecast_temp, day_offset,
                          condition="ABOVE", unit="C")

A versao anterior chamava com kwargs inexistentes (forecast_c=, sigma=,
target=) que nao existem na assinatura atual — causava TypeError em runtime.

build_sigma() e to_celsius() agora existem em model.py (adicionados na
correcao da versao v3).
"""

from datetime import datetime, timezone
from gamma_parser import fetch_markets
from forecast import get_corrected_forecast
from model import build_sigma, calculate_probability, to_celsius
from config import CITY_SLUGS, EDGE_THRESHOLD, MAX_FORECAST_DAY, MIN_PROB_ABOVE_BELOW


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


print("=" * 80)
print("TESTE DE DIAGNOSTICO")
print("=" * 80)
print(f"Data/Hora: {utcnow()}")
print(f"Edge minimo: {EDGE_THRESHOLD * 100:.1f}%")
print(f"Prob minima ABOVE/BELOW: {MIN_PROB_ABOVE_BELOW * 100:.0f}%")
print()

for city in CITY_SLUGS[:3]:
    print(f"\n{city.upper()}")
    print("-" * 80)

    markets = fetch_markets(city)
    print(f"Mercados encontrados: {len(markets)}")

    if not markets:
        print("PROBLEMA: Nenhum mercado encontrado.")
        continue

    for i, market in enumerate(markets[:3]):
        condition    = market.get("condition", "ABOVE").upper()
        unit         = market.get("unit", "C")
        target       = float(market.get("target", 0))
        market_price = float(market.get("yes_price", 0))
        market_date  = market.get("market_date", "")

        try:
            mdate        = datetime.strptime(market_date, "%Y-%m-%d").date()
            forecast_day = max(1, min((mdate - utcnow().date()).days, MAX_FORECAST_DAY))
        except Exception:
            forecast_day = 1

        result = get_corrected_forecast(city, forecast_day)
        if result is None or result[0] is None:
            print(f"  Mercado #{i+1}: forecast indisponivel")
            continue
        forecast_c, raw_sigma, bias = result

        sigma_total = build_sigma(
            city_slug=city,
            forecast_day=forecast_day,
            raw_sigma=raw_sigma,
            condition=condition,
        )

        if sigma_total is None:
            print(f"  Mercado #{i+1}: sigma bloqueado (raw_sigma={raw_sigma:.2f} acima do cap)")
            continue

        # CORRIGIDO: assinatura correta — city, target_temp, forecast_temp, day_offset,
        # condition, unit. Nao existem kwargs forecast_c=, sigma=, target=.
        model_prob = calculate_probability(
            city=city,
            target_temp=target,
            forecast_temp=forecast_c,
            day_offset=forecast_day,
            condition=condition,
            unit=unit,
        )

        edge   = round(model_prob - market_price, 4)
        ev_pct = round((model_prob / market_price - 1) * 100, 1) if market_price > 0 else 0

        target_c = to_celsius(target, unit)
        zscore   = abs(forecast_c - target_c) / max(sigma_total, 0.1)

        print(f"\n  Mercado #{i+1}: {market.get('question','')[:60]}...")
        print(f"    Data: {market_date} | D{forecast_day} | {condition} {target}°{unit}")
        print(f"    Forecast: {forecast_c:.1f}C | Sigma: {sigma_total:.2f} | Z: {zscore:.2f}")
        print(f"    Model: {model_prob*100:.1f}% | Mkt: {market_price*100:.1f}% | Edge: {edge*100:+.1f}%")

        bloqueios = []
        if condition in ("ABOVE", "BELOW"):
            if model_prob < MIN_PROB_ABOVE_BELOW:
                bloqueios.append(f"prob {model_prob:.3f} < {MIN_PROB_ABOVE_BELOW}")
            if zscore < 1.5:
                bloqueios.append(f"zscore {zscore:.2f} < 1.5")
        if edge < EDGE_THRESHOLD:
            bloqueios.append(f"edge {edge:.3f} < {EDGE_THRESHOLD}")

        if not bloqueios:
            print(f"    -> BOM TRADE (passaria por todos os filtros)")
        else:
            print(f"    -> BLOQUEADO: {' | '.join(bloqueios)}")

print("\n" + "=" * 80)
print("FIM DO DIAGNOSTICO")
print("=" * 80)
