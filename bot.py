#!/usr/bin/env python3
"""
Weather Quant Bot v3 — Paper trading real na Polymarket.

CORRIGIDO:
- Importação de _save_to_db, get_open_trades, update_trade de bankroll:
  _save_to_db é função interna do módulo PostgreSQL e não deve ser
  importada aqui. Substituída por record_trade() (função pública).
  get_open_trades e update_trade agora existem em bankroll.py.
- get_forecast() retorna (forecast_c, sigma), não um float — o código
  agora desempacota corretamente antes de passar para calculate_probability.
- calculate_probability agora recebe os parâmetros corretos da assinatura v3.
"""

import logging
import time
import json
import os
import sys
import schedule
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
from risk import kelly_criterion, check_guardrails
from bankroll import record_trade, get_open_trades, update_trade, load_bankroll
from settlement import settle_all
from notificador import notificar_entrada_trade, iniciar_listener
from consensus import ConsensusEngine

from config import (
    TRADING_ENABLED,
    MAX_OPEN_TRADES,
    MAX_TOTAL_EXPOSURE,
    MAX_POSITION,
    CITIES,
)

consensus_engine = ConsensusEngine()

if not CITIES:
    logger.error("Nenhuma cidade disponível.")
    sys.exit(1)

logger.info(f"Bot iniciado | {len(CITIES)} cidades | Trading: {bool(TRADING_ENABLED)}")


def _open_exposure() -> float:
    """Retorna exposição total dos trades abertos."""
    return sum(float(t.get("stake", 0)) for t in get_open_trades())


def process_city(city: Dict):
    name = city["name"]
    logger.info(f"Processando: {name}")

    try:
        markets = fetch_markets(name)
    except Exception as e:
        logger.error(f"fetch_markets({name}): {e}")
        return

    if not markets:
        logger.debug(f"{name}: sem mercados")
        return

    logger.info(f"{name}: {len(markets)} mercados encontrados")

    data    = load_bankroll()
    history = data.get("history", [])

    for m in markets:
        try:
            condition   = m.get("condition", "above").upper()
            target      = float(m.get("target", 0))
            unit        = m.get("unit", "C")
            market_date = m.get("market_date", "")
            market_id   = str(m.get("market_id", ""))
            yes_price   = float(m.get("yes_price", 0))

            # Evita duplicatas
            if any(t.get("market_id") == market_id for t in history):
                continue

            # Limite de trades abertos
            open_trades = get_open_trades()
            if len(open_trades) >= MAX_OPEN_TRADES:
                logger.info("Limite de trades abertos atingido")
                break

            # Limite de exposição
            exposure = _open_exposure()
            if exposure >= MAX_TOTAL_EXPOSURE:
                logger.info(f"Exposição máxima atingida: ${exposure:.2f}")
                break

            # Calcula forecast_day a partir da data de mercado
            try:
                mdate        = datetime.strptime(market_date, "%Y-%m-%d").date()
                forecast_day = max(1, min((mdate - datetime.utcnow().date()).days, 3))
            except Exception:
                forecast_day = 1

            # CORRIGIDO: get_corrected_forecast retorna (forecast_c, raw_sigma, bias)
            result = get_corrected_forecast(name.lower().replace(" ", "-"), forecast_day)
            if result is None or result[0] is None:
                continue
            forecast_c, raw_sigma, bias_c = result

            # Consenso entre fontes
            date_str = market_date
            cons = consensus_engine.consensus_temperature(
                city["lat"], city["lon"], date_str, forecast_c
            )
            if not cons["consensus"]:
                logger.info(f"{name} {condition}: sem consenso — {cons['reason']}")
                continue

            # CORRIGIDO: passa forecast_c (float), não a tupla inteira
            model_prob = calculate_probability(
                city=name,
                target_temp=target,
                forecast_temp=forecast_c,
                day_offset=forecast_day,
                condition=condition,
                unit=unit,
            )

            edge = model_prob - yes_price
            if edge <= 0:
                continue

            # Verifica guardrails
            market_dict = {
                "condition":   condition,
                "target_temp": target,
                "price":       yes_price,
                "day_offset":  forecast_day,
            }
            if not check_guardrails(market_dict, model_prob, forecast_c):
                continue

            # Calcula stake
            stake = min(kelly_criterion(model_prob, yes_price), MAX_POSITION)
            if stake <= 0:
                continue

            # Garante que não estoura exposição
            stake = min(stake, MAX_TOTAL_EXPOSURE - exposure)
            if stake <= 0:
                continue

            shares    = int(stake / yes_price) if yes_price > 0 else 0
            real_cost = round(shares * yes_price, 2)
            stake     = real_cost
            if stake <= 0 or shares <= 0:
                continue

            trade = {
                "id":           f"{market_id}_{int(time.time())}",
                "market_id":    market_id,
                "city":         name,
                "question":     m.get("question", ""),
                "market_date":  market_date,
                "entry_time":   datetime.utcnow().isoformat(),
                "exit_time":    None,
                "type":         condition,
                "unit":         unit,
                "target":       target,
                "forecast_c":   round(forecast_c, 2),
                "sigma_total":  raw_sigma,
                "shares":       shares,
                "forecast_day": forecast_day,
                "model_prob":   round(model_prob, 4),
                "market_price": yes_price,
                "edge":         round(edge, 4),
                "ev":           round(model_prob / yes_price - 1, 4) if yes_price > 0 else 0,
                "stake":        stake,
                "result":       "OPEN",
                "pnl":          0,
                "fee":          0.0,
                "real_temp_c":  None,
            }

            if TRADING_ENABLED:
                # CORRIGIDO: usa record_trade() em vez de _save_to_db()
                record_trade(trade)
                logger.info(
                    f"TRADE: {name} {condition} {target}°{unit} | "
                    f"prob={model_prob:.3f} edge={edge:.3f} stake=${stake:.2f}"
                )
                try:
                    notificar_entrada_trade(
                        city=name, market_date=market_date,
                        target=target, unit=unit, stake=stake,
                        model_prob=model_prob, market_price=yes_price,
                        edge=edge, shares=shares,
                    )
                except Exception as e:
                    logger.warning(f"Telegram: {e}")
            else:
                logger.info(
                    f"SINAL: {name} {condition} {target}°{unit} | "
                    f"prob={model_prob:.3f} edge={edge:.3f} stake=${stake:.2f}"
                )

        except Exception as e:
            logger.error(f"{name} mercado {m.get('market_id','?')}: {e}", exc_info=True)


def settlement_cycle():
    logger.info("Iniciando ciclo de liquidação...")
    try:
        settle_all()
    except Exception as e:
        logger.error(f"Liquidação: {e}", exc_info=True)


def scheduled_trading():
    logger.info(f"=== CICLO {datetime.utcnow():%Y-%m-%d %H:%M:%S UTC} ===")
    for city in CITIES:
        try:
            process_city(city)
        except Exception as e:
            logger.error(f"{city.get('name','?')}: {e}", exc_info=True)
    logger.info("=== FIM DO CICLO ===")


def run():
    # Inicia listener Telegram em background
    try:
        iniciar_listener()
    except Exception as e:
        logger.warning(f"Listener Telegram não iniciado: {e}")

    schedule.every(1).hours.do(scheduled_trading)
    schedule.every(1).hours.do(settlement_cycle)

    # Executa imediatamente no início
    scheduled_trading()

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    logger.info("Weather Quant Bot v3 iniciado")
    run()
