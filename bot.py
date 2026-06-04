#!/usr/bin/env python3
"""
bot.py — Weather Quant Bot v5.5

v5.5: Correções de bugs
v5.4: Suporte a apostas NO
- Após avaliar YES, avalia também NO para cada mercado
- NO: apostamos quando mercado paga muito para YES mas modelo discorda
- Exemplos: Toronto ABOVE 28°C mkt=0.725 prob=0.21 → NO edge=0.51
            Miami BELOW 85°F mkt=0.914 prob=0.23 → NO edge=0.68
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
from risk import (
    kelly_criterion, kelly_criterion_no,
    check_guardrails, dynamic_kelly_fraction,
)

from bankroll import load_bankroll, save_bankroll, already_traded
from settlement import settle_all
from notificador import notificar_entrada_trade, iniciar_listener
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
    f"Weather Quant Bot v5.5 | {len(cities)} cidades | "
    f"Trading: {'ON' if TRADING_ENABLED else 'OFF (observação)'}"
)


def _get_open_trades(history):
    return [t for t in history if t.get("result") == "OPEN"]


def process_city(city: Dict):
    name = city["name"]
    logger.info(f"Processando: {name}")

    city_slug = name.lower().replace(" ", "-")

    if not city_is_reliable(city_slug):
        logger.info(f"{name}: cidade não confiável — pulando")
        return

    try:
        markets = fetch_markets(city_slug)
    except Exception as e:
        logger.error(f"fetch_markets({city_slug}): {e}")
        return

    if not markets:
        logger.debug(f"{name}: sem mercados")
        return

    logger.info(f"{name}: {len(markets)} mercados válidos encontrados")

    data    = load_bankroll()
    history = data.get("history", [])
    balance = float(data.get("balance", 0))

    for m in markets:
        try:
            market_date = m.get("market_date", "")
            market_id   = str(m.get("market_id", ""))

            # Checagem de duplicata — cobre IDs com sufixo _YES/_NO e sem sufixo (trades antigos)
            yes_traded = already_traded(history, market_id + "_YES") or already_traded(history, market_id)
            no_traded  = already_traded(history, market_id + "_NO")
            if yes_traded and no_traded:
                logger.debug(f"Já negociado (ambos lados): {market_id}")
                continue

            open_count = len(_get_open_trades(history))
            if open_count >= MAX_OPEN_TRADES:
                logger.info(f"Limite de {MAX_OPEN_TRADES} trades abertos atingido")
                break

            exposure = sum(float(t.get("stake", 0)) for t in _get_open_trades(history))
            if exposure >= MAX_TOTAL_EXPOSURE:
                logger.info(f"Exposição máxima ${MAX_TOTAL_EXPOSURE:.2f} atingida")
                break

            date_str = market_date if isinstance(market_date, str) else str(market_date)

            # Fix: calcula day_offset ANTES de buscar forecast para usar sigma correto
            day_offset = 1
            try:
                from datetime import timezone as _tz
                mdate      = datetime.strptime(date_str, "%Y-%m-%d").date()
                today_utc  = datetime.now(_tz.utc).date()
                day_offset = max(0, (mdate - today_utc).days)
                day_offset = max(1, day_offset)
            except Exception:
                pass

            forecast_result = get_corrected_forecast(city_slug, day_offset)
            if forecast_result is None or forecast_result[0] is None:
                logger.debug(f"Forecast indisponível para {name}")
                continue

            forecast_c, sigma, bias = forecast_result

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
            target_lo  = m.get("target_lo")
            target_hi  = m.get("target_hi")

            # Confirmação intra-dia para D+0
            if day_offset <= 1 and condition in ("ABOVE", "BELOW"):
                target_c_check = (target - 32) * 5 / 9 if unit == "F" else target
                intra = get_intraday_confirmation(city_slug, condition, target_c_check)
                if intra["confirmed"] is False:
                    logger.info(f"{name}: intra-dia negativo — {intra['reason']}")
                    continue
                if intra["confirmed"] is True:
                    logger.info(f"{name}: intra-dia POSITIVO — {intra['reason']}")

            # Calcula probabilidade
            prob = calculate_probability(
                city=name,
                target_temp=target,
                forecast_temp=forecast_c,
                day_offset=day_offset,
                condition=condition,
                unit=unit,
                sigma=sigma,
                target_lo=target_lo,
                target_hi=target_hi,
            )

            edge_yes = prob - yes_price
            edge_no  = yes_price - prob  # NO edge: quanto mkt paga a mais

            logger.info(
                f"  {condition} {target}°{unit} | "
                f"forecast={forecast_c:.1f}°C | "
                f"prob={prob:.3f} mkt={yes_price:.3f} "
                f"edge_YES={edge_yes:+.3f} edge_NO={edge_no:+.3f}"
            )

            market_dict = {
                "condition":   condition,
                "target_temp": target,
                "price":       yes_price,
                "day_offset":  day_offset,
                "unit":        unit,
            }

            # --- AVALIAR YES ---
            if edge_yes > 0 and not yes_traded:
                if check_guardrails(market_dict, prob, forecast_c, sigma=sigma, side="YES"):
                    kf    = dynamic_kelly_fraction(history)
                    stake = kelly_criterion(prob, yes_price, balance, fraction=kf)
                    _execute_trade(
                        data, history, balance, name, m, date_str, condition,
                        target, unit, yes_price, prob, edge_yes, stake,
                        day_offset, sigma, forecast_c, target_lo, target_hi,
                        market_id + "_YES", side="YES",
                    )
                    # Recarrega após trade
                    data    = load_bankroll()
                    history = data.get("history", [])
                    balance = float(data.get("balance", 0))

            # --- AVALIAR NO ---
            if edge_no > 0 and not already_traded(history, market_id + "_NO"):
                if check_guardrails(market_dict, prob, forecast_c, sigma=sigma, side="NO"):
                    kf    = dynamic_kelly_fraction(history)
                    stake = kelly_criterion_no(prob, yes_price, balance, fraction=kf)
                    _execute_trade(
                        data, history, balance, name, m, date_str, condition,
                        target, unit, yes_price, prob, edge_no, stake,
                        day_offset, sigma, forecast_c, target_lo, target_hi,
                        market_id + "_NO", side="NO",
                    )
                    data    = load_bankroll()
                    history = data.get("history", [])
                    balance = float(data.get("balance", 0))

        except Exception as e:
            logger.error(f"{name} mercado {m.get('market_id','?')}: {e}", exc_info=True)


def _execute_trade(
    data, history, balance, name, m, date_str, condition,
    target, unit, yes_price, prob, edge, stake,
    day_offset, sigma, forecast_c, target_lo, target_hi,
    trade_id, side="YES",
):
    """Registra e notifica um trade YES ou NO."""
    if stake <= 0:
        return

    if side == "YES":
        entry_price = yes_price
        shares = int(stake / entry_price) if entry_price > 0 else 0
    else:
        # NO: compra NO a price_no = 1 - yes_price
        entry_price = round(1.0 - yes_price, 4)
        shares = int(stake / entry_price) if entry_price > 0 else 0

    real_cost = round(shares * entry_price, 2)
    stake = real_cost

    if stake <= 0:
        return

    trade = dict(
        market_id    = trade_id,
        city         = name,
        question     = m.get("question", ""),
        market_date  = date_str,
        entry_time   = datetime.utcnow().isoformat(),
        exit_time    = None,
        type         = condition,
        side         = side,
        unit         = unit,
        target       = target,
        target_lo    = target_lo,
        target_hi    = target_hi,
        forecast_c   = forecast_c,
        sigma_total  = round(sigma, 4),
        shares       = shares,
        model_prob   = round(prob, 4),
        market_price = yes_price,
        entry_price  = entry_price,
        edge         = round(edge, 4),
        ev           = round((1.0 - prob) * (1.0 / entry_price - 1.0) - prob, 4) if side == "NO" and entry_price > 0 else
                       round(prob * (1.0 / yes_price - 1.0) - (1.0 - prob), 4) if yes_price > 0 else 0,
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
            f"TRADE [{side}]: {name} {condition} {target}°{unit} | "
            f"prob={prob:.3f} edge={edge:.3f} stake=${stake:.2f} "
            f"price_{side}={entry_price:.3f}"
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
            f"SINAL [{side}]: {name} {condition} {target}°{unit} | "
            f"prob={prob:.3f} edge={edge:.3f} stake=${stake:.2f}"
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
    try:
        iniciar_listener()
        logger.info("Listener Telegram iniciado")
    except Exception as e:
        logger.warning(f"Listener Telegram não iniciado: {e}")

    schedule.every(1).hours.do(scheduled_trading)
    schedule.every(1).hours.do(settlement_cycle)
    scheduled_trading()
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    logger.info("Weather Quant Bot v5.5")
    run()
