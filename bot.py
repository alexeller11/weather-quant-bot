#!/usr/bin/env python3
"""
Weather Quant Bot v4 — Paper trading real na Polymarket.

CORREÇÕES v4:
  1. calculate_probability() agora recebe condition= e unit= para usar
     a fórmula correta por tipo de mercado (ABOVE/BELOW/EXACT).

  2. kelly_criterion() agora recebe balance= (saldo real) em vez de
     usar bankroll hardcoded de $100.

  3. check_guardrails() recebe unit= para converter target para °C
     internamente antes de calcular zscore.
"""

import logging, time, json, os, sys, schedule
from datetime import datetime
from typing import Dict, List, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("bot")

from gamma_parser import fetch_markets
from forecast import get_corrected_forecast
from model import calculate_probability
from risk import kelly_criterion, check_guardrails, dynamic_kelly_fraction

from bankroll import load_bankroll, save_bankroll, already_traded
from settlement import settle_all
from notificador import notificar_entrada_trade
from consensus import ConsensusEngine
from station_data import get_intraday_confirmation, city_is_reliable

from config import (
    TRADING_ENABLED,
    MAX_OPEN_TRADES,
    MAX_TOTAL_EXPOSURE,
    MAX_POSITION,
    CITIES,
)

consensus_engine = ConsensusEngine()
cities = CITIES

if not cities:
    logger.error("Nenhuma cidade disponível.")
    sys.exit(1)

logger.info(
    f"Weather Quant Bot v4 | {len(cities)} cidades | "
    f"Trading: {'ON' if TRADING_ENABLED else 'OFF (observação)'}"
)


def _get_open_trades(history):
    return [t for t in history if t.get("result") == "OPEN"]


def process_city(city: Dict):
    name = city["name"]
    logger.info(f"Processando: {name}")

    city_slug = name.lower().replace(" ", "-")

    # Ignora cidades com histórico de erro de forecast muito alto
    if not city_is_reliable(city_slug):
        logger.info(f"{name}: cidade não confiável (erro histórico > 5°C) — pulando")
        return

    try:
        markets = fetch_markets(city_slug)
    except Exception as e:
        logger.error(f"fetch_markets({city_slug}): {e}")
        return

    if not markets:
        logger.debug(f"{name}: sem mercados")
        return

    logger.info(f"{name}: {len(markets)} mercados")

    for m in markets:
        try:
            # Recarrega bankroll a cada mercado para evitar race condition
            # (saldo e exposição podem mudar entre iterações)
            data    = load_bankroll()
            history = data.get("history", [])
            balance = float(data.get("balance", 0))

            market_date = m.get("market_date", "")
            market_id   = str(m.get("market_id", ""))

            if already_traded(history, market_id):
                logger.debug(f"Já negociado: {market_id}")
                continue

            open_count = len(_get_open_trades(history))
            if open_count >= MAX_OPEN_TRADES:
                logger.info(f"Limite de {MAX_OPEN_TRADES} trades abertos atingido")
                break

            exposure = sum(float(t.get("stake", 0)) for t in _get_open_trades(history))
            if exposure >= MAX_TOTAL_EXPOSURE:
                logger.info(f"Exposição máxima ${MAX_TOTAL_EXPOSURE:.2f} atingida")
                break

            forecast_result = get_corrected_forecast(name.lower().replace(" ", "-"), 1)
            if forecast_result is None or forecast_result[0] is None:
                logger.debug(f"Forecast indisponível para {name}")
                continue

            forecast_c, sigma, bias = forecast_result

            date_str = market_date if isinstance(market_date, str) else str(market_date)

            cons = consensus_engine.consensus_temperature(
                city["lat"], city["lon"], date_str, forecast_c
            )
            if not cons["consensus"]:
                logger.info(f"{name}: {cons['reason']}")
                continue

            condition  = m.get("condition", "above").upper()
            target     = float(m.get("target", 0))
            unit       = m.get("unit", "C")
            yes_price  = float(m.get("yes_price", 0))

            day_offset = 1
            try:
                from datetime import date as _date
                mdate      = datetime.strptime(date_str, "%Y-%m-%d").date()
                day_offset = max(1, (mdate - datetime.utcnow().date()).days)
            except Exception:
                pass

            # Para mercados do dia atual (D+0/D+1): verifica tendência intra-dia.
            # Se max do dia já passou target (ABOVE) → certeza alta.
            # Se tarde e bem abaixo do target → rejeita.
            if day_offset <= 1:
                target_c_check = (target - 32) * 5 / 9 if unit == "F" else target
                intra = get_intraday_confirmation(city_slug, condition, target_c_check)
                if intra["confirmed"] is False:
                    logger.info(
                        f"{name}: confirmação intra-dia negativa — {intra['reason']}"
                    )
                    continue
                if intra["confirmed"] is True:
                    logger.info(
                        f"{name}: confirmação intra-dia POSITIVA — {intra['reason']}"
                    )

            # Passa sigma do forecast (com ajustes climáticos por cidade)
            # para evitar recálculo inconsistente em model.py e risk.py
            prob = calculate_probability(
                city=name,
                target_temp=target,
                forecast_temp=forecast_c,
                day_offset=day_offset,
                condition=condition,
                unit=unit,
                sigma=sigma,
            )

            edge = prob - yes_price
            if edge <= 0:
                continue

            market_dict = {
                "condition":   condition,
                "target_temp": target,
                "price":       yes_price,
                "day_offset":  day_offset,
                "unit":        unit,
            }
            if not check_guardrails(market_dict, prob, forecast_c, sigma=sigma):
                continue

            # Kelly dinâmico: reduz fração após perdas consecutivas
            kf    = dynamic_kelly_fraction(history)
            stake = kelly_criterion(prob, yes_price, balance, fraction=kf)
            if stake <= 0:
                continue

            shares    = int(stake / yes_price) if yes_price > 0 else 0
            real_cost = round(shares * yes_price, 2)
            stake     = real_cost

            if stake <= 0:
                continue

            trade = dict(
                market_id    = market_id,
                city         = name,
                question     = m.get("question", ""),
                market_date  = date_str,
                entry_time   = datetime.utcnow().isoformat(),
                exit_time    = None,
                type         = condition,
                unit         = unit,
                target       = target,
                forecast_c   = forecast_c,
                sigma_total  = round(sigma, 4),
                shares       = shares,
                model_prob   = round(prob, 4),
                market_price = yes_price,
                edge         = round(edge, 4),
                ev           = round(prob / yes_price - 1, 4) if yes_price > 0 else 0,
                stake        = stake,
                result       = "OPEN",
                pnl          = 0,
                fee          = 0.0,
                forecast_day = day_offset,
                real_temp_c  = None,
            )

            if TRADING_ENABLED:
                history.append(trade)
                balance -= stake
                data["history"] = history
                data["balance"] = round(balance, 4)
                save_bankroll(data)
                logger.info(
                    f"TRADE: {name} {condition} {target}°{unit} | "
                    f"prob={prob:.3f} edge={edge:.3f} stake=${stake:.2f}"
                )
                try:
                    notificar_entrada_trade(
                        city=name, market_date=date_str, target=target,
                        unit=unit, stake=stake, model_prob=prob,
                        market_price=yes_price, edge=edge,
                        balance=balance, shares=shares,
                    )
                except Exception:
                    pass
            else:
                logger.info(
                    f"SINAL: {name} {condition} {target}°{unit} | "
                    f"prob={prob:.3f} edge={edge:.3f} stake=${stake:.2f}"
                )

        except Exception as e:
            logger.error(
                f"{name} mercado {m.get('market_id','?')}: {e}", exc_info=True
            )


def settlement_cycle():
    logger.info("Iniciando liquidação...")
    try:
        settle_all()
    except Exception as e:
        logger.error(f"Liquidação: {e}", exc_info=True)


def scheduled_trading():
    logger.info(f"Ciclo de trading: {datetime.now():%H:%M:%S}")
    for city in cities:
        try:
            process_city(city)
        except Exception as e:
            logger.error(f"{city.get('name','?')}: {e}", exc_info=True)
    logger.info("Fim do ciclo")


def run():
    schedule.every(1).hours.do(scheduled_trading)
    schedule.every(1).hours.do(settlement_cycle)
    scheduled_trading()
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    logger.info("Weather Quant Bot v4")
    run()
