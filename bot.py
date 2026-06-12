#!/usr/bin/env python3
"""
bot.py — Weather Quant Bot v5.6

v5.6: Correções estruturais
- Chaves canônicas para evitar duplicidade de mercados e trades
- Slug de cidade normalizado (São Paulo -> sao-paulo)
- Day offset corrigido (hoje = 1, amanhã = 2)
- Deduplicação de mercados repetidos vindos da Gamma API
- Histórico deduplicado para cálculo de risco / Kelly

CORREÇÕES (auditoria):
1. O day_offset do mercado agora é calculado contra o DIA LOCAL da
   cidade (city_today), não contra a data UTC. Para cidades da Ásia o
   dia UTC fica até 9h atrasado: um mercado de "hoje" em Tóquio era
   tratado como D+1 (sigma maior, sem confirmação intra-dia).
2. Registro de trade via bankroll.record_trade(): operação atômica
   (lock de thread + arquivo + advisory lock no Postgres) e idempotente
   por chave única. O padrão antigo load→append→save sem lock perdia
   atualizações quando o listener do Telegram (thread) ou o settlement
   (subprocesso) salvavam o bankroll ao mesmo tempo — causa direta da
   divergência de saldo observada nos dados (-$19.80).
3. Exposição: o stake é CLAMPADO ao headroom de MAX_TOTAL_EXPOSURE.
   Antes o check era `exposure >= MAX` ANTES do trade, permitindo
   estourar o teto em até +MAX_POSITION (ex.: 19.99 + 4.00 = 23.99).
4. Limite por EVENTO (cidade+data): buckets do mesmo evento são
   mutuamente exclusivos; o stake somado neles agora respeita
   MAX_EVENT_EXPOSURE (default = MAX_POSITION). Evita o caso real de
   3 posições YES EXACT no mesmo dia de Toronto (todas perdedoras menos,
   no máximo, uma — por construção).
5. EV gravado no trade agora é o EV líquido COM fee (mesma fórmula dos
   guardrails), e o EV do lado NO usa a fórmula correta
   (prob_no·b − prob_yes; a antiga tinha sinal invertido).
6. entry_time agora é timezone-aware UTC (datetime.now(timezone.utc)).
"""

import logging
import time
import os
import sys
import schedule
from datetime import datetime, timezone
from typing import Dict

from bankroll import (
    load_bankroll,
    save_bankroll,
    already_traded,
    dedupe_history_by_market,
    canonical_market_base,
    normalize_city_slug,
    record_trade,
)
from consensus import ConsensusEngine
from forecast import get_corrected_forecast, city_today
from gamma_parser import fetch_markets
from model import calculate_probability
from notificador import iniciar_listener, notificar_entrada_trade
from risk import (
    check_guardrails,
    dynamic_kelly_fraction,
    kelly_criterion,
    kelly_criterion_no,
    expected_value,
    expected_value_no,
    exposure_headroom,
    event_headroom,
)
from settlement import settle_all
from station_data import city_is_reliable, get_intraday_confirmation
from config import (
    TRADING_ENABLED,
    MAX_OPEN_TRADES,
    MAX_TOTAL_EXPOSURE,
    MAX_POSITION,
    CITIES,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("bot")

consensus_engine = ConsensusEngine()
cities = CITIES

if not cities:
    logger.error("Nenhuma cidade disponível.")
    sys.exit(1)

logger.info(
    f"Weather Quant Bot v5.6 | {len(cities)} cidades | "
    f"Trading: {'ON' if TRADING_ENABLED else 'OFF (observação)'}"
)


def _get_open_trades(history):
    history_view = dedupe_history_by_market(history)
    return [t for t in history_view if t.get("result") == "OPEN"]


def _forecast_day_for_market(market_date: str, city_slug: str) -> int:
    """
    Hoje (LOCAL da cidade) = 1, amanhã = 2, etc.
    O mercado da Polymarket resolve pelo dia local da cidade, então a
    referência de "hoje" precisa ser o calendário local — não o UTC.
    """
    try:
        mdate = datetime.strptime(market_date, "%Y-%m-%d").date()
        local_today = datetime.strptime(city_today(city_slug), "%Y-%m-%d").date()
        return max(1, (mdate - local_today).days + 1)
    except Exception:
        return 1


def process_city(city: Dict):
    name = city["name"]
    logger.info(f"Processando: {name}")

    city_slug = normalize_city_slug(name)

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

    forecast_cache = {}  # forecast_day -> (forecast_c, sigma, bias)
    for m in markets:
        date_str = str(m.get("market_date", ""))
        forecast_day = _forecast_day_for_market(date_str, city_slug)
        if forecast_day not in forecast_cache:
            result = get_corrected_forecast(city_slug, forecast_day)
            forecast_cache[forecast_day] = result
            if result is None or result[0] is None:
                logger.debug(f"Forecast indisponível para {name} D+{forecast_day-1}")
            else:
                logger.debug(
                    f"Forecast {name} D+{forecast_day-1}: {result[0]:.1f}°C sigma={result[1]:.2f}"
                )

    data = load_bankroll()
    history = data.get("history", [])
    history_view = dedupe_history_by_market(history)
    balance = float(data.get("balance", 0))

    seen_market_keys = set()

    for m in markets:
        try:
            market_date = str(m.get("market_date", ""))
            condition = str(m.get("condition", "above")).upper()
            target = float(m.get("target", 0))
            unit = str(m.get("unit", "C")).upper()
            target_lo = m.get("target_lo")
            target_hi = m.get("target_hi")
            market_base = str(
                m.get("market_id")
                or canonical_market_base(
                    city=name,
                    market_date=market_date,
                    condition=condition,
                    target=target,
                    unit=unit,
                    target_lo=target_lo,
                    target_hi=target_hi,
                )
            )

            if market_base in seen_market_keys:
                logger.debug(f"{name}: mercado duplicado no ciclo — {market_base}")
                continue
            seen_market_keys.add(market_base)

            yes_trade_id = f"{market_base}_YES"
            no_trade_id = f"{market_base}_NO"

            yes_traded = already_traded(history, yes_trade_id)
            no_traded = already_traded(history, no_trade_id)
            if yes_traded and no_traded:
                logger.debug(f"Já negociado (ambos lados): {market_base}")
                continue

            open_trades = _get_open_trades(history_view)
            open_count = len(open_trades)
            if open_count >= MAX_OPEN_TRADES:
                logger.info(f"Limite de {MAX_OPEN_TRADES} trades abertos atingido")
                break

            exposure = sum(float(t.get("stake", 0)) for t in open_trades)
            total_headroom = exposure_headroom(exposure)
            if total_headroom <= 0:
                logger.info(f"Exposição máxima ${MAX_TOTAL_EXPOSURE:.2f} atingida")
                break

            # Headroom do EVENTO (cidade+data): buckets mutuamente exclusivos
            ev_headroom = event_headroom(open_trades, name, market_date)
            if ev_headroom <= 0:
                logger.info(
                    f"{name} {market_date}: limite por evento atingido — pulando bucket"
                )
                continue

            stake_cap = min(total_headroom, ev_headroom)

            forecast_day = _forecast_day_for_market(market_date, city_slug)
            forecast_result = forecast_cache.get(forecast_day)
            if forecast_result is None or forecast_result[0] is None:
                logger.debug(f"Forecast indisponível para {name} D+{forecast_day-1}")
                continue

            forecast_c, sigma, bias = forecast_result

            cons = consensus_engine.consensus_temperature(
                city["lat"], city["lon"], market_date, forecast_c,
                condition=condition,
            )
            if not cons["consensus"]:
                logger.info(f"{name}: {cons['reason']}")
                continue

            yes_price = float(m.get("yes_price", 0))
            target_lo = m.get("target_lo")
            target_hi = m.get("target_hi")

            # Confirmação intra-dia para o mercado de hoje.
            if forecast_day == 1 and condition in ("ABOVE", "BELOW"):
                target_c_check = (target - 32) * 5 / 9 if unit == "F" else target
                intra = get_intraday_confirmation(city_slug, condition, target_c_check)
                if intra["confirmed"] is False:
                    logger.info(f"{name}: intra-dia negativo — {intra['reason']}")
                    continue
                if intra["confirmed"] is True:
                    logger.info(f"{name}: intra-dia POSITIVO — {intra['reason']}")

            prob = calculate_probability(
                city=name,
                target_temp=target,
                forecast_temp=forecast_c,
                day_offset=forecast_day,
                condition=condition,
                unit=unit,
                sigma=sigma,
                target_lo=target_lo,
                target_hi=target_hi,
            )

            edge_yes = prob - yes_price
            edge_no  = yes_price - prob

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
                "day_offset":  forecast_day,
                "unit":        unit,
            }

            # --- AVALIAR YES ---
            if edge_yes > 0 and not yes_traded:
                if check_guardrails(market_dict, prob, forecast_c, sigma=sigma, side="YES"):
                    kf = dynamic_kelly_fraction(history_view)
                    stake = kelly_criterion(prob, yes_price, balance, fraction=kf)
                    stake = min(stake, stake_cap)
                    _execute_trade(
                        name, m, market_date, condition,
                        target, unit, yes_price, prob, edge_yes, stake,
                        forecast_day, sigma, forecast_c, target_lo, target_hi,
                        yes_trade_id, side="YES",
                    )
                    data = load_bankroll()
                    history = data.get("history", [])
                    history_view = dedupe_history_by_market(history)
                    balance = float(data.get("balance", 0))

            # --- AVALIAR NO ---
            if edge_no > 0 and not no_traded:
                if check_guardrails(market_dict, prob, forecast_c, sigma=sigma, side="NO"):
                    kf = dynamic_kelly_fraction(history_view)
                    stake = kelly_criterion_no(prob, yes_price, balance, fraction=kf)
                    # Recalcula headroom com estado pós-YES deste mesmo bucket
                    open_trades = _get_open_trades(history_view)
                    exposure = sum(float(t.get("stake", 0)) for t in open_trades)
                    stake_cap_no = min(
                        exposure_headroom(exposure),
                        event_headroom(open_trades, name, market_date),
                    )
                    stake = min(stake, stake_cap_no)
                    _execute_trade(
                        name, m, market_date, condition,
                        target, unit, yes_price, prob, edge_no, stake,
                        forecast_day, sigma, forecast_c, target_lo, target_hi,
                        no_trade_id, side="NO",
                    )
                    data = load_bankroll()
                    history = data.get("history", [])
                    history_view = dedupe_history_by_market(history)
                    balance = float(data.get("balance", 0))

        except Exception as e:
            logger.error(f"{name} mercado {m.get('market_id','?')}: {e}", exc_info=True)


def _execute_trade(
    name, m, date_str, condition,
    target, unit, yes_price, prob, edge, stake,
    day_offset, sigma, forecast_c, target_lo, target_hi,
    trade_id, side="YES",
):
    """Registra (atomicamente) e notifica um trade YES ou NO."""
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

    market_key = trade_id
    if market_key.endswith("_YES"):
        market_key = market_key[:-4]
    elif market_key.endswith("_NO"):
        market_key = market_key[:-3]

    # EV líquido por $1 apostado, COM fee — consistente com os guardrails.
    if side == "NO":
        ev_net = expected_value_no(prob, yes_price)
    else:
        ev_net = expected_value(prob, yes_price)

    trade = dict(
        market_id      = trade_id,
        market_key     = market_key,
        gamma_market_id = str(m.get("gamma_market_id", "")),
        gamma_event_id = str(m.get("gamma_event_id", "")),
        city           = name,
        question       = m.get("question", ""),
        market_date    = date_str,
        event_slug     = m.get("event_slug", ""),
        entry_time     = datetime.now(timezone.utc).isoformat(),
        exit_time      = None,
        type           = condition,
        side           = side,
        unit           = unit,
        target         = target,
        target_lo      = target_lo,
        target_hi      = target_hi,
        forecast_c     = forecast_c,
        sigma_total    = round(sigma, 4),
        shares         = shares,
        model_prob     = round(prob, 4),
        market_price   = yes_price,
        entry_price    = entry_price,
        edge           = round(edge, 4),
        ev             = round(ev_net, 4),
        stake          = stake,
        result         = "OPEN",
        pnl            = 0,
        fee            = 0.0,
        forecast_day   = day_offset,
        real_temp_c    = None,
    )

    if TRADING_ENABLED:
        # record_trade: append + débito do stake numa única seção crítica,
        # idempotente por chave única do trade.
        recorded = record_trade(trade)
        if not recorded:
            logger.info(f"TRADE NÃO registrado (duplicado?): {trade_id}")
            return
        new_balance = float(load_bankroll().get("balance", 0))
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
                balance=new_balance, shares=shares,
            )
        except Exception:
            pass
    else:
        logger.info(
            f"SINAL [{side}]: {name} {condition} {target}°{unit} | "
            f"prob={prob:.3f} edge={edge:.3f} stake=${stake:.2f}"
        )


def weekly_report_cycle():
    """Envia relatório semanal todo domingo às 08:00 UTC."""
    if datetime.now(timezone.utc).weekday() != 6:  # 6 = domingo
        return
    logger.info("Enviando relatório semanal...")
    try:
        from weekly_report import gerar_relatorio_semanal
        gerar_relatorio_semanal(enviar_telegram=True)
    except Exception as e:
        logger.error(f"Relatório semanal: {e}", exc_info=True)


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
    schedule.every().sunday.at("08:00").do(weekly_report_cycle)
    settlement_cycle()
    scheduled_trading()
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    logger.info("Weather Quant Bot v5.6")
    run()
