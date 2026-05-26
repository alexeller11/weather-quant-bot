#!/usr/bin/env python3
"""
Weather Quant Bot v3 - Loop principal com consenso, calibração e ML.
Paper trading real na Polymarket com dinheiro fictício.
Totalmente compatível com as funções reais do projeto.
"""

import logging
import time
import json
import os
import sys
import schedule
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("bot")

# ============================================================
# Importações - usando nomes REAIS dos arquivos
# ============================================================

# gamma_parser: função fetch_markets(city_name)
from gamma_parser import fetch_markets

# forecast: classe ForecastService
from forecast import ForecastService

# model: funções calculate_probability, get_calibrator, get_ml_adjuster
from model import calculate_probability

# risk: funções kelly_criterion, check_guardrails
from risk import kelly_criterion, check_guardrails

# bankroll: funções save_trade, get_open_trades
from bankroll import save_trade, get_open_trades

# settlement: função settle_all
from settlement import settle_all

# notificador: função notify_trade
from notificador import notify_trade

# NOVO: motor de consenso
from consensus import ConsensusEngine

# Configurações
try:
    from config import (
        TRADING_ENABLED, MAX_OPEN_TRADES, MAX_TOTAL_EXPOSURE,
        MIN_PROB_ABOVE_BELOW, MIN_TARGET_ZSCORE, MAX_POSITION,
        KELLY_FRACTION, CITIES
    )
except ImportError:
    TRADING_ENABLED = 0
    MAX_OPEN_TRADES = 4
    MAX_TOTAL_EXPOSURE = 8.0
    MIN_PROB_ABOVE_BELOW = 0.70
    MIN_TARGET_ZSCORE = 1.50
    MAX_POSITION = 2.00
    KELLY_FRACTION = 0.50
    CITIES = []

# ============================================================
# Inicialização
# ============================================================

# Instanciar serviços
forecast_service = ForecastService()
consensus_engine = ConsensusEngine()

# Estado global
cities = CITIES
open_trades = []

if not cities:
    logger.error("Nenhuma cidade disponível. Bot não pode operar.")
    sys.exit(1)

logger.info(f"🤖 Bot iniciado com {len(cities)} cidades.")
logger.info(f"💰 Paper trading: {'ATIVADO' if TRADING_ENABLED else 'DESLIGADO'}")
logger.info(f"📊 Parâmetros: MAX_POSITION=${MAX_POSITION}, MAX_OPEN={MAX_OPEN_TRADES}, MAX_EXPOSURE=${MAX_TOTAL_EXPOSURE}")

# ============================================================
# Funções principais
# ============================================================

def get_total_exposure() -> float:
    """Calcula a exposição total atual."""
    total = 0.0
    for trade in open_trades:
        if trade.get('status') == 'OPEN':
            total += trade.get('stake', 0)
    return total

def process_city(city: Dict):
    """Processa uma cidade: coleta, avalia e opcionalmente executa trades."""
    city_name = city.get('name', 'unknown')
    logger.info(f"📍 Processando: {city_name}")

    # Buscar mercados (nome real da função: fetch_markets)
    try:
        markets = fetch_markets(city_name)
    except Exception as e:
        logger.error(f"❌ Erro ao buscar mercados para {city_name}: {e}")
        return

    if not markets:
        logger.debug(f"📭 Nenhum mercado ativo para {city_name}")
        return

    logger.info(f"📋 {len(markets)} mercados encontrados para {city_name}")

    for market in markets:
        try:
            market_id = market.get('id', 'unknown')
            condition = market.get('condition', '?')
            target_temp = market.get('target_temp', 0)
            price = market.get('price', 0)
            market_date = market.get('date')
            day_offset = market.get('day_offset', 1)

            # 1. Previsão de temperatura (ForecastService.get_forecast)
            forecast_temp = forecast_service.get_forecast(city, market_date)
            if forecast_temp is None:
                logger.debug(f"🌡️ Previsão indisponível para {city_name} em {market_date}")
                continue

            # 2. Consenso multi-fonte
            date_str = market_date.strftime('%Y-%m-%d') if isinstance(market_date, datetime) else str(market_date)
            consensus = consensus_engine.consensus_temperature(
                lat=city['lat'],
                lon=city['lon'],
                date_str=date_str,
                temp_openmeteo=forecast_temp,
                threshold=3.0
            )
            if not consensus['consensus']:
                logger.info(f"🚫 Consenso bloqueou {city_name} {condition}: {consensus['reason']}")
                continue

            # 3. Modelagem probabilística
            model_prob = calculate_probability(
                city=city_name,
                target_temp=target_temp,
                forecast_temp=forecast_temp,
                day_offset=day_offset
            )

            # 4. Edge
            edge = model_prob - price
            if edge <= 0:
                logger.debug(f"📉 Edge negativo para {city_name} {condition}: {edge:.3f}")
                continue

            # 5. Guardrails
            if not check_guardrails(market, model_prob, forecast_temp):
                continue

            # 6. Verificar exposição
            current_exposure = get_total_exposure()
            if current_exposure >= MAX_TOTAL_EXPOSURE:
                logger.info(f"🚫 Exposição máxima atingida: ${current_exposure:.2f}")
                continue

            if len([t for t in open_trades if t.get('status') == 'OPEN']) >= MAX_OPEN_TRADES:
                logger.info(f"🚫 Máximo de trades abertos atingido: {MAX_OPEN_TRADES}")
                continue

            # 7. Kelly Criterion
            stake = kelly_criterion(model_prob, price)
            if stake <= 0:
                continue

            # Aplicar cap de posição
            stake = min(stake, MAX_POSITION)
            remaining_exposure = MAX_TOTAL_EXPOSURE - current_exposure
            stake = min(stake, remaining_exposure)

            # 8. Executar trade
            if TRADING_ENABLED:
                trade = {
                    "id": f"{market_id}_{int(time.time())}",
                    "city": city_name,
                    "lat": city['lat'],
                    "lon": city['lon'],
                    "condition": condition,
                    "target_temp": target_temp,
                    "forecast_temp": forecast_temp,
                    "model_prob": round(model_prob, 4),
                    "price": price,
                    "stake": round(stake, 2),
                    "edge": round(edge, 4),
                    "date": date_str,
                    "day_offset": day_offset,
                    "status": "OPEN",
                    "timestamp": datetime.now().isoformat()
                }

                # Salvar trade
                try:
                    save_trade(trade)
                    open_trades.append(trade)
                    logger.info(f"✅ Trade executado: {city_name} {condition} {target_temp}°F | "
                                f"prob={model_prob:.3f} | edge={edge:.3f} | stake=${stake:.2f}")

                    # Notificar (com proteção contra erro de assinatura)
                    try:
                        notify_trade(trade, edge, consensus)
                    except TypeError:
                        try:
                            notify_trade(trade)
                        except Exception:
                            logger.debug("Notificação desativada ou incompatível")
                    except Exception as e:
                        logger.debug(f"Erro ao notificar: {e}")

                except Exception as e:
                    logger.error(f"❌ Erro ao salvar trade: {e}")
            else:
                logger.info(f"📊 Sinal PAPER: {city_name} {condition} {target_temp}°F | "
                            f"prob={model_prob:.3f} | edge={edge:.3f} | stake=${stake:.2f}")

        except Exception as e:
            logger.error(f"❌ Erro processando mercado {market.get('id', '?')}: {e}", exc_info=True)
            continue

def settlement_cycle():
    """Executa liquidação de trades abertos periodicamente."""
    global open_trades
    logger.info("🔄 Iniciando ciclo de liquidação...")

    try:
        # Chamar settle_all do módulo settlement
        settle_all()
        
        # Recarregar trades abertos
        try:
            open_trades = get_open_trades()
            open_count = len([t for t in open_trades if t.get('status') == 'OPEN'])
            won_count = len([t for t in open_trades if t.get('status') == 'WON'])
            lost_count = len([t for t in open_trades if t.get('status') == 'LOST'])
            logger.info(f"📊 Trades: {open_count} abertos | {won_count} ganhos | {lost_count} perdidos")
        except Exception as e:
            logger.debug(f"Não foi possível recarregar trades: {e}")

    except Exception as e:
        logger.error(f"❌ Erro no ciclo de liquidação: {e}", exc_info=True)

def scheduled_trading():
    """Ciclo de trading para todas as cidades."""
    logger.info(f"=== 🚀 CICLO DE TRADING INICIADO: {datetime.now().strftime('%H:%M:%S')} ===")

    success_count = 0
    error_count = 0

    for city in cities:
        try:
            process_city(city)
            success_count += 1
        except Exception as e:
            logger.error(f"❌ Erro em {city.get('name', 'unknown')}: {e}", exc_info=True)
            error_count += 1

    logger.info(f"=== ✅ CICLO CONCLUÍDO: {success_count} cidades processadas, {error_count} erros ===")

def run():
    """Loop principal agendado."""
    # Agendar ciclos
    schedule.every(1).hours.do(scheduled_trading)
    schedule.every(1).hours.do(settlement_cycle)

    # Executar primeiro ciclo imediatamente
    logger.info("🎯 Executando primeiro ciclo de trading...")
    scheduled_trading()

    logger.info(f"⏰ Próximo ciclo em 1 hora. Aguardando...")
    while True:
        schedule.run_pending()
        time.sleep(30)

# ============================================================
# Ponto de entrada
# ============================================================
if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("🌤️  WEATHER QUANT BOT v3")
    logger.info("📈 Paper Trading na Polymarket")
    logger.info("=" * 60)
    run()