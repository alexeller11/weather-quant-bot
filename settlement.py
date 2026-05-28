#!/usr/bin/env python3
"""
Settlement Engine — Liquidação de trades com base em temperaturas reais.

CORRIGIDO:
- Importava bankroll.get_open_trades() e bankroll.update_trade() que não
  existiam em bankroll.py. Agora existem — importação direta corrigida.
- settle_trade() adaptado para trabalhar com a estrutura de trade do bot v3
  (campos 'market_date', 'city', 'type', 'target', 'unit', 'stake', etc.)
- Notificações Telegram integradas (win/loss/resumo).
- Atualiza calibrador de sigma e modelo ML após cada liquidação.
"""

import logging
import json
import os
import requests
from datetime import datetime, timezone
from typing import Dict, Optional

from sigma_calibrator import SigmaCalibrator
from ml_adjuster import MLProbabilityAdjuster
from model import get_calibrator, get_ml_adjuster
from bankroll import load_bankroll, save_bankroll, get_open_trades, update_trade

logger = logging.getLogger("settlement")

_calibrator  = get_calibrator()
_ml_adjuster = get_ml_adjuster()


# ──────────────────────────────────────────────────────────────
# TEMPERATURA REAL
# ──────────────────────────────────────────────────────────────

def get_actual_temperature(lat: float, lon: float, date: str) -> Optional[float]:
    """Consulta temperatura máxima real na Open-Meteo Archive API."""
    try:
        url = "https://archive-api.open-meteo.com/v1/archive"
        params = {
            "latitude":   lat,
            "longitude":  lon,
            "start_date": date,
            "end_date":   date,
            "daily":      "temperature_2m_max",
            "timezone":   "UTC",
        }
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        temp = data["daily"]["temperature_2m_max"][0]
        if temp is None:
            raise ValueError("Temperatura ausente na resposta")
        return float(temp)
    except Exception as e:
        logger.error(f"Temperatura real indisponível para ({lat},{lon}) em {date}: {e}")
        return None


def _get_city_coordinates(city_name: str) -> tuple:
    """Busca coordenadas em cities.json, depois no fallback de config."""
    try:
        cities_path = os.path.join(os.path.dirname(__file__), "cities.json")
        with open(cities_path, "r") as f:
            cities = json.load(f)
        for city in cities:
            if city["name"].lower() == city_name.lower():
                return city["lat"], city["lon"]
    except Exception as e:
        logger.warning(f"cities.json: {e}")

    # Fallback: config.py
    try:
        from config import CITIES
        for city in CITIES:
            if city["name"].lower() == city_name.lower():
                return city["lat"], city["lon"]
    except Exception:
        pass

    logger.error(f"Coordenadas não encontradas para: {city_name}")
    return None, None


# ──────────────────────────────────────────────────────────────
# VERIFICAÇÃO DE DATA
# ──────────────────────────────────────────────────────────────

def _trade_is_ready(trade: Dict) -> bool:
    """
    Retorna True se o trade pode ser liquidado hoje.
    Um trade está pronto quando market_date < hoje (UTC).
    """
    market_date_str = trade.get("market_date", "")
    if not market_date_str:
        return False
    try:
        market_date = datetime.strptime(market_date_str, "%Y-%m-%d").date()
        today_utc   = datetime.now(timezone.utc).date()
        return market_date < today_utc
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────
# LIQUIDAÇÃO DE TRADE INDIVIDUAL
# ──────────────────────────────────────────────────────────────

def settle_trade(trade: Dict, bankroll_data: Dict) -> Dict:
    """
    Liquida um trade, atualiza calibrador e ML, aplica PnL ao bankroll.
    Retorna o trade atualizado.
    """
    result_field = trade.get("result")
    if result_field != "OPEN":
        return trade

    if not _trade_is_ready(trade):
        return trade

    city        = trade.get("city", "")
    market_date = trade.get("market_date", "")
    condition   = (trade.get("type") or "ABOVE").upper()
    target      = float(trade.get("target", 0))
    unit        = (trade.get("unit") or "C").upper()
    stake       = float(trade.get("stake", 0))
    market_price = float(trade.get("market_price", 0))
    model_prob  = float(trade.get("model_prob") or 0.5)
    forecast_c  = trade.get("forecast_c")
    day_offset  = trade.get("forecast_day", 1)

    # Coordenadas (preferência: campos lat/lon no trade)
    lat = trade.get("lat")
    lon = trade.get("lon")
    if lat is None or lon is None:
        lat, lon = _get_city_coordinates(city)
    if lat is None:
        logger.error(f"Sem coordenadas para {city} — trade não liquidado")
        return trade

    # Temperatura real
    actual_temp_c = get_actual_temperature(lat, lon, market_date)
    if actual_temp_c is None:
        logger.warning(f"Temperatura indisponível: {city} {market_date}")
        return trade

    # Converte target para Celsius para comparação uniforme
    if unit == "F":
        target_c = (target - 32) * 5 / 9
    else:
        target_c = target

    # Verifica se trade venceu
    if condition == "ABOVE":
        won = actual_temp_c > target_c
    elif condition == "BELOW":
        won = actual_temp_c < target_c
    else:  # EXACT
        won = abs(actual_temp_c - target_c) <= 0.5

    # Calcula PnL
    if won:
        if market_price > 0:
            gross = stake / market_price
            fee   = round(gross * 0.02, 4)
            pnl   = round(gross - stake - fee, 4)
        else:
            fee = 0.0
            pnl = 0.0
    else:
        fee = 0.0
        pnl = round(-stake, 4)

    exit_time = datetime.now(timezone.utc).isoformat()

    # Atualiza trade
    trade = dict(trade)
    trade["result"]     = "WIN" if won else "LOSS"
    trade["pnl"]        = pnl
    trade["fee"]        = fee
    trade["real_temp_c"] = actual_temp_c
    trade["exit_time"]  = exit_time

    # Atualiza saldo no bankroll
    bankroll_data["balance"] = round(
        float(bankroll_data.get("balance", 0)) + pnl, 4
    )

    logger.info(
        f"{'WIN' if won else 'LOSS'}: {city} {condition} {target}°{unit} "
        f"| real={actual_temp_c:.1f}C | PnL={pnl:+.2f}"
    )

    # Atualiza calibrador e ML
    if forecast_c is not None:
        try:
            _calibrator.record_trade_result(
                city=city,
                day_offset=day_offset,
                predicted_temp=float(forecast_c),
                actual_temp=actual_temp_c,
            )
            _ml_adjuster.update(
                model_prob=model_prob,
                day_offset=day_offset,
                city=city,
                calibrator=_calibrator,
                trade_success=won,
            )
        except Exception as e:
            logger.warning(f"Calibração: {e}")

    # Notifica via Telegram
    try:
        saldo = bankroll_data.get("balance", 0)
        if won:
            from notificador import notificar_settlement_win
            notificar_settlement_win(
                city=city, market_date=market_date, target=target, unit=unit,
                stake=stake, pnl=pnl, saldo=saldo,
                model_prob=model_prob, real_temp_c=actual_temp_c,
            )
        else:
            from notificador import notificar_settlement_loss
            notificar_settlement_loss(
                city=city, market_date=market_date, target=target, unit=unit,
                stake=stake, pnl=pnl, saldo=saldo,
                model_prob=model_prob, real_temp_c=actual_temp_c,
            )
    except Exception as e:
        logger.warning(f"Telegram settlement: {e}")

    return trade


# ──────────────────────────────────────────────────────────────
# CICLO COMPLETO
# ──────────────────────────────────────────────────────────────

def settle_all():
    """Liquida todos os trades OPEN que já têm data passada."""
    bankroll_data = load_bankroll()
    history       = bankroll_data.get("history", [])

    open_trades = [t for t in history if t.get("result") == "OPEN"]
    ready       = [t for t in open_trades if _trade_is_ready(t)]

    if not ready:
        logger.info(
            f"Settlement: {len(open_trades)} trades abertos, "
            f"nenhum pronto para liquidar."
        )
        return

    logger.info(f"Settlement: liquidando {len(ready)} de {len(open_trades)} abertos")

    wins   = 0
    losses = 0
    total_pnl = 0.0
    changed = False

    for i, trade in enumerate(history):
        if trade.get("result") != "OPEN" or not _trade_is_ready(trade):
            continue
        updated = settle_trade(trade, bankroll_data)
        if updated["result"] in ("WIN", "LOSS"):
            history[i] = updated
            changed = True
            if updated["result"] == "WIN":
                wins += 1
            else:
                losses += 1
            total_pnl += float(updated.get("pnl", 0))

    if changed:
        bankroll_data["history"] = history
        save_bankroll(bankroll_data)
        logger.info(
            f"Settlement concluído: {wins}W/{losses}L | "
            f"PnL={total_pnl:+.2f} | "
            f"Saldo=${bankroll_data.get('balance', 0):.2f}"
        )
        if wins + losses > 0:
            try:
                from notificador import notificar_settlement_resumo
                notificar_settlement_resumo(
                    total_resolved=wins + losses,
                    wins=wins,
                    losses=losses,
                    total_pnl=total_pnl,
                    saldo=bankroll_data.get("balance", 0),
                )
            except Exception as e:
                logger.warning(f"Telegram resumo: {e}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    settle_all()
