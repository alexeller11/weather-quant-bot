#!/usr/bin/env python3
"""
bot.py — Weather Quant Bot

Loop principal: para cada cidade ATIVA de cities.json, busca os mercados
D+0/D+1 na Gamma API, calcula probabilidade, passa pelos guardrails de
risco e registra o trade (ou o sinal, quando TRADING_ENABLED=0).

Só cidades ativas geram novas entradas; a liquidação continua a cobrir
todas (ver config.build_city_maps).
"""

import logging
import time
import os
import sys
import threading
import schedule
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
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
    check_balance_invariant,
)
from consensus import ConsensusEngine
from forecast import get_corrected_forecast, city_today
from gamma_parser import fetch_markets
from model import calculate_probability
from notificador import iniciar_listener, notificar_entrada_trade, notificar_quase_trade
from paper_execution import simulate_paper_buy
from risk import (
    check_guardrails,
    dynamic_kelly_fraction,
    kelly_criterion,
    kelly_criterion_no,
    expected_value,
    expected_value_no,
    exposure_headroom,
    event_headroom,
    risk_limits_ok,
    trading_cooldown,
    city_trading_cooldown,
)
from settlement import settle_all
from station_data import city_is_reliable, get_intraday_confirmation
from config import (
    TRADING_ENABLED,
    PAPER_EXECUTION_REQUIRED,
    MAX_OPEN_TRADES,
    MAX_TOTAL_EXPOSURE,
    MAX_POSITION,
    MAX_FORECAST_DAY,
    MIN_EDGE_NO,
    MIN_TRADE_STAKE,
    REQUIRE_CONSENSUS,
    CITIES,
)
from config import resolution_coords
from decision_log import record_decision
from analytics.manager import analytics_manager
from analytics.reports import text as analytics_report_text

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
    f"Weather Quant Bot | {len(cities)} cidades ativas | "
    f"Trading: {'ON' if TRADING_ENABLED else 'OFF (observação)'}"
)


def _get_open_trades(history):
    history_view = dedupe_history_by_market(history)
    return [t for t in history_view if t.get("result") == "OPEN"]


def _forecast_day_for_market(market_date: str, city_slug: str) -> int:
    """
    Hoje (LOCAL da cidade) = 1, amanhã = 2, etc.
    """
    try:
        mdate = datetime.strptime(market_date, "%Y-%m-%d").date()
        local_today = datetime.strptime(city_today(city_slug), "%Y-%m-%d").date()
        return max(1, (mdate - local_today).days + 1)
    except Exception:
        return 1


def process_city(city: Dict):
    name = city["display"]
    logger.info(f"Processando: {name}")

    city_slug = normalize_city_slug(name)

    if not city_is_reliable(city_slug):
        record_decision("blocked", "city_unreliable", city=name)
        logger.info(f"{name}: cidade não confiável — pulando")
        return

    # Circuit breaker por cidade
    data = load_bankroll()
    on_cooldown, reason = city_trading_cooldown(data.get("history", []), name)
    if on_cooldown:
        record_decision("blocked", "city_cooldown", city=name, detail=reason)
        logger.warning(f"{name}: em cooldown individual — {reason}")
        return

    try:
        markets = fetch_markets(city_slug)
    except Exception as e:
        record_decision("error", "fetch_markets_error", city=name, error=str(e))
        logger.error(f"fetch_markets({city_slug}): {e}")
        return

    if not markets:
        record_decision("blocked", "no_markets", city=name)
        logger.info(f"{name}: sem mercados saudáveis na Polymarket")
        return

    logger.info(f"{name}: {len(markets)} mercados válidos encontrados")

    forecast_cache = {}
    for m in markets:
        date_str = str(m.get("market_date", ""))
        from datetime import date as _dt
        try:
            _md = _dt.fromisoformat(date_str[:10])
            if _md < _dt.today():
                record_decision("blocked", "market_expired", city=name, market_date=date_str)
                continue
        except (ValueError, TypeError):
            pass
        forecast_day = _forecast_day_for_market(date_str, city_slug)
        if forecast_day not in forecast_cache:
            result = get_corrected_forecast(city_slug, forecast_day)
            forecast_cache[forecast_day] = result
            # Pequeno delay se não for cache hit (ajuda contra 429)
            time.sleep(0.3)
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
    start_balance = float(data.get("start_balance", balance))

    ok, reason = risk_limits_ok(history_view, balance, start_balance)
    if not ok:
        record_decision("blocked", "risk_limit", city=name, detail=reason)
        logger.warning(f"{name}: novas entradas bloqueadas por risco — {reason}")
        return

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
                record_decision("blocked", "duplicate_market_in_cycle", city=name, market=m)
                logger.debug(f"{name}: mercado duplicado no ciclo — {market_base}")
                continue
            seen_market_keys.add(market_base)

            yes_trade_id = f"{market_base}_YES"
            no_trade_id = f"{market_base}_NO"

            yes_traded = already_traded(history, yes_trade_id)
            no_traded = already_traded(history, no_trade_id)
            if yes_traded and no_traded:
                record_decision("blocked", "already_traded_both_sides", city=name, market=m)
                logger.debug(f"Já negociado (ambos lados): {market_base}")
                continue

            open_trades = _get_open_trades(history_view)
            ok, reason = risk_limits_ok(history_view, balance, start_balance)
            if not ok:
                record_decision("blocked", "risk_limit", city=name, market=m, detail=reason)
                logger.warning(f"{name}: bloqueado por risco — {reason}")
                break
            open_count = len(open_trades)
            if open_count >= MAX_OPEN_TRADES:
                record_decision("blocked", "max_open_trades", city=name, market=m, open_count=open_count)
                logger.info(f"Limite de {MAX_OPEN_TRADES} trades abertos atingido")
                break

            exposure = sum(float(t.get("stake", 0)) for t in open_trades)
            total_headroom = exposure_headroom(exposure)
            if total_headroom <= 0:
                record_decision("blocked", "max_total_exposure", city=name, market=m, exposure=exposure)
                logger.info(f"Exposição máxima ${MAX_TOTAL_EXPOSURE:.2f} atingida")
                break

            ev_headroom = event_headroom(open_trades, name, market_date)
            if ev_headroom <= 0:
                record_decision("blocked", "event_exposure_limit", city=name, market=m)
                logger.info(
                    f"{name} {market_date}: limite por evento atingido — pulando bucket"
                )
                continue

            stake_cap = min(total_headroom, ev_headroom)

            forecast_day = _forecast_day_for_market(market_date, city_slug)
            # MAX_FORECAST_DAY existia em config mas nunca era verificado.
            if forecast_day > MAX_FORECAST_DAY:
                record_decision("blocked", "forecast_day_alem_do_horizonte",
                                city=name, market=m, forecast_day=forecast_day)
                continue

            forecast_result = forecast_cache.get(forecast_day)
            if forecast_result is None or forecast_result[0] is None:
                record_decision("blocked", "forecast_unavailable", city=name, market=m, forecast_day=forecast_day)
                logger.debug(f"Forecast indisponível para {name} D+{forecast_day-1}")
                continue

            forecast_c, sigma, bias, forecast_c_raw = forecast_result

            # Consenso na MESMA coordenada usada para forecast e liquidação.
            cons_lat, cons_lon = resolution_coords(city)
            cons = consensus_engine.consensus_temperature(
                cons_lat, cons_lon, market_date, forecast_c_raw,
                condition=condition, city=name,
            )
            if not cons["consensus"]:
                record_decision("blocked", "consensus_failed", city=name, market=m, detail=cons.get("reason"))
                logger.info(f"{name}: {cons['reason']}")
                continue
            # REQUIRE_CONSENSUS=1 exige confirmação de 2ª fonte. Sem isto o
            # consenso passava por omissão em todo o histórico (nunca houve
            # WEATHERAPI_KEY configurada), o que tornava o motor decorativo.
            if REQUIRE_CONSENSUS and cons.get("temp_secondary") is None:
                record_decision("blocked", "consensus_indisponivel", city=name, market=m,
                                detail=cons.get("reason"))
                logger.info(f"{name}: 2a fonte indisponivel e REQUIRE_CONSENSUS=1 — pulando")
                continue

            yes_price = float(m.get("yes_price", 0))
            target_lo = m.get("target_lo")
            target_hi = m.get("target_hi")

            if forecast_day == 1 and condition in ("ABOVE", "BELOW"):
                target_c_check = (target - 32) * 5 / 9 if unit == "F" else target
                intra = get_intraday_confirmation(city_slug, condition, target_c_check)
                if intra["confirmed"] is False:
                    record_decision("blocked", "intraday_negative", city=name, market=m, detail=intra.get("reason"))
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
                "target_lo":   target_lo,
                "target_hi":  target_hi,
            }

            # --- AVALIAR YES ---
            if edge_yes > 0 and not yes_traded:
                ok, reason = check_guardrails(market_dict, prob, forecast_c, sigma=sigma, side="YES")
                if ok:
                    kf = dynamic_kelly_fraction(history_view)
                    stake = kelly_criterion(prob, yes_price, balance, fraction=kf, city=name)
                    stake = min(stake, stake_cap)
                    _execute_trade(
                        name, m, market_date, condition,
                        target, unit, yes_price, prob, edge_yes, stake,
                        forecast_day, sigma, forecast_c, target_lo, target_hi,
                        yes_trade_id, side="YES",
                        forecast_c_raw=forecast_c_raw,
                    )
                    data = load_bankroll()
                    history = data.get("history", [])
                    history_view = dedupe_history_by_market(history)
                    balance = float(data.get("balance", 0))
                else:
                    record_decision(
                        "blocked", reason, city=name, market=m, side="YES",
                        prob=prob, edge=edge_yes, yes_price=yes_price, sigma=sigma,
                        forecast_c=forecast_c, forecast_c_raw=forecast_c_raw,
                        forecast_day=forecast_day,
                    )

            # --- AVALIAR NO ---
            if edge_no > 0 and not no_traded:
                ok, reason = check_guardrails(market_dict, prob, forecast_c, sigma=sigma, side="NO")
                if ok:
                    kf = dynamic_kelly_fraction(history_view)
                    stake = kelly_criterion_no(prob, yes_price, balance, fraction=kf)
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
                        forecast_c_raw=forecast_c_raw,
                    )
                    data = load_bankroll()
                    history = data.get("history", [])
                    history_view = dedupe_history_by_market(history)
                    balance = float(data.get("balance", 0))
                else:
                    # Alerta de Quase-Trade (v5.7)
                    if reason == "edge_insuficiente":
                        if edge_no >= (MIN_EDGE_NO - 0.005):
                            notificar_quase_trade(name, market_date, target, unit, prob, yes_price, edge_no, MIN_EDGE_NO, reason)

                    record_decision(
                        "blocked", reason, city=name, market=m, side="NO",
                        prob=prob, edge=edge_no, yes_price=yes_price, sigma=sigma,
                        forecast_c=forecast_c, forecast_c_raw=forecast_c_raw,
                        forecast_day=forecast_day,
                    )

        except Exception as e:
            logger.error(f"{name} mercado {m.get('market_id','?')}: {e}", exc_info=True)


def _execute_trade(
    name, m, date_str, condition,
    target, unit, yes_price, prob, edge, stake,
    day_offset, sigma, forecast_c, target_lo, target_hi,
    trade_id, side="YES", forecast_c_raw=None,
):
    if stake <= 0:
        record_decision("blocked", "stake_zero", city=name, market=m, side=side, prob=prob, edge=edge, stake=stake)
        return

    # Sem piso, o truncamento de shares mais abaixo produzia posições de
    # $0.20 (15 no histórico) que só poluem a estatística.
    if stake < MIN_TRADE_STAKE:
        record_decision(
            "blocked", "stake_abaixo_do_minimo", city=name, market=m, side=side,
            prob=prob, edge=edge, stake=stake, minimo=MIN_TRADE_STAKE,
        )
        logger.info(f"Stake ${stake:.2f} < minimo ${MIN_TRADE_STAKE:.2f} — pulando")
        return

    execution = None

    # Execução real: só com POLY_PRIV_KEY definida E execução real
    # implementada. Hoje real_execution levanta NotImplementedError de
    # propósito — antes era um stub que devolvia ok=True e o bankroll
    # registrava posições que não existiam.
    is_real_mode = not PAPER_EXECUTION_REQUIRED and os.getenv("POLY_PRIV_KEY")

    if is_real_mode:
        from real_execution import execute_real_trade
        try:
            res = execute_real_trade(m, side, stake)
        except NotImplementedError as exc:
            record_decision("error", "real_execution_nao_implementada", city=name,
                            market=m, side=side, detail=str(exc))
            logger.error(
                "POLY_PRIV_KEY definida mas execucao real nao implementada — "
                "trade NAO registrado. Use PAPER_EXECUTION_REQUIRED=1."
            )
            return
        if res["ok"]:
            entry_price = res["avg_price"]
            shares = res["shares"]
            stake = res["filled_cost"]
            logger.info(f"TRADE REAL EXECUTADO: {side} @ {entry_price}")
        else:
            record_decision("blocked", "real_execution_failed", detail=res["reason"])
            logger.error(f"FALHA NO TRADE REAL: {res['reason']}")
            return

    elif PAPER_EXECUTION_REQUIRED:
        execution = simulate_paper_buy(m, side, stake)
        if not execution.ok:
            record_decision(
                "blocked", "paper_execution_blocked", city=name, market=m, side=side,
                prob=prob, edge=edge, requested_stake=stake, detail=execution.reason,
            )
            logger.info(
                f"PAPER EXEC bloqueado [{side}]: {name} {condition} {target}°{unit} | "
                f"{execution.reason}"
            )
            return
        entry_price = round(execution.avg_price, 4)
        shares = round(execution.shares, 4)
        stake = round(execution.filled_cost, 4)
        logger.info(
            f"PAPER EXEC [{side}]: token={execution.token_id[:10]}... "
            f"avg={entry_price:.4f} best_ask={execution.best_ask:.4f} "
            f"slip={execution.slippage:.4f} shares={shares:.4f}"
        )
    else:
        if side == "YES":
            entry_price = yes_price
        else:
            entry_price = round(1.0 - yes_price, 4)
        shares = int(stake / entry_price) if entry_price > 0 else 0
    if shares <= 0:
        record_decision(
            "blocked", "shares_zero", city=name, market=m, side=side,
            prob=prob, edge=edge, stake=stake, entry_price=entry_price,
        )
        logger.info(
            f"Stake ${stake:.2f} insuficiente para comprar 1 share "
            f"a {entry_price:.3f} ({side})"
        )
        return

    real_cost = round(float(shares) * entry_price, 4)
    stake = real_cost

    if stake <= 0:
        record_decision("blocked", "stake_zero_after_execution", city=name, market=m, side=side, prob=prob, edge=edge)
        return

    if stake < MIN_TRADE_STAKE:
        record_decision(
            "blocked", "stake_abaixo_do_minimo_pos_execucao", city=name, market=m,
            side=side, prob=prob, edge=edge, stake=stake, minimo=MIN_TRADE_STAKE,
        )
        logger.info(
            f"Stake efetivo ${stake:.2f} < minimo ${MIN_TRADE_STAKE:.2f} "
            f"({shares} shares a {entry_price:.3f}) — pulando"
        )
        return

    market_key = trade_id
    if market_key.endswith("_YES"):
        market_key = market_key[:-4]
    elif market_key.endswith("_NO"):
        market_key = market_key[:-3]

    if side == "NO":
        ev_net = expected_value(1.0 - prob, entry_price)
    else:
        ev_net = expected_value(prob, entry_price)

    if side == "NO":
        edge = (1.0 - prob) - entry_price
    else:
        edge = prob - entry_price

    trade = dict(
        market_id      = trade_id,
        market_key     = market_key,
        gamma_market_id = str(m.get("gamma_market_id", "")),
        gamma_event_id = str(m.get("gamma_event_id", "")),
        yes_token_id    = str(m.get("yes_token_id", "")),
        no_token_id     = str(m.get("no_token_id", "")),
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
        forecast_c_raw = forecast_c_raw,  # AUDITORIA bug #1: cru p/ compute_bias
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
    if execution is not None:
        trade.update(execution.as_trade_fields())

    if TRADING_ENABLED:
        recorded = record_trade(trade)
        if not recorded:
            record_decision("blocked", "record_duplicate", city=name, market=m, side=side, market_id=trade_id)
            logger.info(f"TRADE NÃO registrado (duplicado?): {trade_id}")
            return
        record_decision(
            "recorded", "trade_recorded", city=name, market=m, side=side,
            prob=prob, edge=edge, stake=stake, entry_price=entry_price,
            shares=shares, paper_execution=execution is not None,
            slippage=(execution.slippage if execution is not None else None),
            fill_ratio=(execution.fill_ratio if execution is not None else None),
        )
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
        record_decision(
            "signal", "signal_only", city=name, market=m, side=side,
            prob=prob, edge=edge, stake=stake, entry_price=entry_price,
            shares=shares, paper_execution=execution is not None,
            slippage=(execution.slippage if execution is not None else None),
            fill_ratio=(execution.fill_ratio if execution is not None else None),
        )
        logger.info(
            f"SINAL [{side}]: {name} {condition} {target}°{unit} | "
            f"prob={prob:.3f} edge={edge:.3f} stake=${stake:.2f}"
        )


def weekly_report_cycle():
    if datetime.now(timezone.utc).weekday() != 6:
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
        update_analytics()
    except Exception as e:
        logger.error(f"Liquidação: {e}", exc_info=True)


_last_health_alert = {"signature": None, "ts": 0.0}


def health_alert_cycle():
    """
    Envia alerta Telegram quando a saude operacional indica problema.
    Usa throttle por assinatura para nao repetir o mesmo aviso sem parar.
    """
    try:
        from dashboard import load_data
        from operational_health import build_operational_health
        from notificador import enviar_mensagem

        data, warning = load_data()
        health = build_operational_health(data or {}, warning)
        status = health.get("status")
        if status not in ("degraded", "stale", "unknown"):
            return

        reason = health.get("dominant_block_reason") or "none"
        signature = f"{status}|{reason}|{health.get('data_source')}"
        now = time.time()
        if (
            _last_health_alert["signature"] == signature
            and now - _last_health_alert["ts"] < 6 * 3600
        ):
            return

        _last_health_alert["signature"] = signature
        _last_health_alert["ts"] = now
        enviar_mensagem(
            "<b>ALERTA OPERACIONAL</b>\n\n"
            f"Status: <b>{status}</b>\n"
            f"Resumo: {health.get('summary')}\n"
            f"DB ok: {health.get('db_ok')} ({health.get('data_source')})\n"
            f"Ultima decisao: {health.get('last_decision_ts')}\n"
            f"Idade decisao: {health.get('last_decision_age_seconds')}s\n"
            f"Motivo dominante: {reason}\n"
            f"Abertos: {health.get('open_count')} | "
            f"Saldo: ${float(health.get('balance') or 0):.2f}"
        )
    except Exception as e:
        logger.warning(f"health_alert_cycle: {e}")


def scheduled_trading():
    logger.info(f"Ciclo de trading: {datetime.now():%H:%M:%S}")

    # Verifica invariante de bankroll antes de operar.
    # check_balance_invariant já loga WARN acima de $0.05; aqui só
    # escalamos quando a divergência é material ($0.50+).
    try:
        data = load_bankroll()
        diff = check_balance_invariant(data)
        if abs(diff) > 0.50:
            logger.warning(
                f"DIVERGÊNCIA DE BANKROLL: {diff:+.4f} — verifique o histórico"
            )
    except Exception as e:
        logger.warning(f"check_balance_invariant: {e}")

    # Cooldown após consecutive losses — pausa novas entradas (settlement continua)
    try:
        data = load_bankroll()
        history_view = dedupe_history_by_market(data.get("history", []))
        on_cooldown, reason = trading_cooldown(history_view)
        if on_cooldown:
            logger.warning(f"COOLDOWN: {reason} — pulando ciclo de trading")
            return
    except Exception as e:
        logger.warning(f"trading_cooldown check: {e}")

    for i, city in enumerate(cities):
        try:
            process_city(city)
            # Evita Rate Limit (429) na Open-Meteo e Polymarket
            if i < len(cities) - 1:
                time.sleep(1.5)
        except Exception as e:
            logger.error(f"{city.get('display','?')}: {e}", exc_info=True)

    logger.info("Fim do ciclo")

    # Estado final do ciclo
    end_data = load_bankroll()
    end_open = [t for t in end_data.get("history", []) if t.get("result") == "OPEN"]
    logger.info(f"[CYCLE] Fim: {len(end_open)} abertos, saldo=${end_data.get('balance',0):.2f}")


# ── Dashboard HTTP server (satisfaz Render + serve dashboard) ────
_dashboard_httpd = None
_dashboard_error = None
# Sinalizado quando o listener está de pé OU falhou. Sem isto, run() lia
# _dashboard_error imediatamente após thread.start() — nunca estaria
# preenchido, e a verificação não verificava nada.
_dashboard_ready = threading.Event()


def _start_dashboard_server():
    """Arranca o servidor HTTP do dashboard em porta dinâmica (Render)."""
    global _dashboard_httpd, _dashboard_error
    try:
        from dashboard import Handler

        PORT = int(os.environ.get("PORT", "10000"))

        # Classe wrapper que combina rotas do dashboard + healthz
        class _CombinedHandler(Handler):
            def do_GET(self):
                if self.path in ("/healthz", "/health"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain")
                    self.end_headers()
                    self.wfile.write(b"ok")
                    return
                # Resto: delega ao Handler original (/, /api/stats)
                super().do_GET()

        _dashboard_httpd = HTTPServer(("0.0.0.0", PORT), _CombinedHandler)
        logger.info(f"Dashboard HTTP listener na porta {PORT}")
        _dashboard_ready.set()
        _dashboard_httpd.serve_forever()
    except Exception as exc:
        _dashboard_error = exc
        logger.warning(f"[dashboard] erro no servidor HTTP: {exc}")
        _dashboard_ready.set()


def run():
    # Arranca dashboard em thread separada (satisfaz port scan + serve UI)
    t = threading.Thread(target=_start_dashboard_server, daemon=True)
    t.start()
    # Espera o listener subir (ou falhar) antes de decidir.
    if not _dashboard_ready.wait(timeout=20):
        logger.warning("[dashboard] listener não sinalizou em 20s — seguindo")
    elif _dashboard_error:
        raise RuntimeError(f"[dashboard] nao foi possivel iniciar: {_dashboard_error}")
    else:
        logger.info("Dashboard + health-check HTTP listener iniciado")

    # Teste de bloqueio geográfico da Polymarket
    try:
        r_geo = requests.get("https://clob.polymarket.com/markets/0x123", timeout=5)
        if r_geo.status_code == 403:
            logger.error("BLOQUEIO GEOGRÁFICO: o IP deste servidor está bloqueado pela Polymarket.")
            from notificador import enviar_mensagem
            enviar_mensagem(
                "<b>ALERTA:</b> o servidor está numa região bloqueada pela "
                "Polymarket. O bot não conseguirá operar sem proxy."
            )
        else:
            logger.info("Conexão com Polymarket validada (sem bloqueio geográfico).")
    except Exception as e:
        logger.warning(f"Teste de geobloqueio falhou: {e}")

    try:
        iniciar_listener()
        logger.info("Listener Telegram iniciado")
    except Exception as e:
        logger.warning(f"Listener Telegram não iniciado: {e}")

    schedule.every(1).hours.do(scheduled_trading)
    schedule.every(1).hours.do(settlement_cycle)
    schedule.every(30).minutes.do(health_alert_cycle)
    schedule.every().sunday.at("08:00").do(weekly_report_cycle)
    # Trading PRIMEIRO, settlement DEPOIS — evita race condition onde
    # settlement fecha trades que acabaram de ser abertos no mesmo ciclo.
    scheduled_trading()
    health_alert_cycle()
    logger.info("Aguardando 120s antes da primeira liquidação...")
    time.sleep(120)
    settlement_cycle()

    while True:
        schedule.run_pending()
        time.sleep(30)


# ── Analytics helpers ─────────────────────────────────────────

def update_analytics():
    """
    Atualiza o Analytics a partir do bankroll atual.
    """
    try:
        analytics_manager.run(load_bankroll())
        logger.info("Analytics atualizado.")
    except Exception as exc:
        logger.exception("Analytics: %s", exc)


def analytics_report():
    """
    Retorna relatório textual do Analytics.
    """
    analytics_manager.update(load_bankroll())
    return analytics_report_text(analytics_manager.report())

if __name__ == "__main__":
    logger.info("Weather Quant Bot — arrancando")
    run()
