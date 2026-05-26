#!/usr/bin/env python3
"""
Settlement Engine - Liquidação de trades com base em resultados reais.
Atualiza calibrador de sigma e modelo ML.
"""

import logging
import json
import os
import requests
from datetime import datetime
from typing import Dict, Optional

from sigma_calibrator import SigmaCalibrator
from ml_adjuster import MLProbabilityAdjuster
from model import get_calibrator, get_ml_adjuster

# FIX: bankroll não exporta get_open_trades() nem update_trade().
# Usar load_bankroll / save_bankroll que são a API pública real.
from bankroll import load_bankroll, save_bankroll

from notificador import (
    notificar_settlement_win,
    notificar_settlement_loss,
    notificar_settlement_resumo,
)

logger = logging.getLogger("settlement")

_calibrator  = get_calibrator()
_ml_adjuster = get_ml_adjuster()


def get_actual_temperature(lat: float, lon: float, date: str) -> Optional[float]:
    """Consulta a temperatura máxima real na Open-Meteo Archive API."""
    try:
        url = "https://archive-api.open-meteo.com/v1/archive"
        params = {
            "latitude":   lat,
            "longitude":  lon,
            "start_date": date,
            "end_date":   date,
            "daily":      "temperature_2m_max",
            "timezone":   "auto",
        }
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        temp = data["daily"]["temperature_2m_max"][0]
        if temp is None:
            raise ValueError("Temperatura ausente na resposta")
        return float(temp)
    except Exception as e:
        logger.error(f"Falha ao obter temperatura real para ({lat},{lon}) em {date}: {e}")
        return None


def _get_city_coordinates(city_name: str):
    """Busca coordenadas da cidade no cities.json ou em config.py."""
    try:
        cities_path = os.path.join(os.path.dirname(__file__), "cities.json")
        with open(cities_path, "r") as f:
            cities = json.load(f)
        for city in cities:
            if city["name"].lower() == city_name.lower():
                return city["lat"], city["lon"]
    except Exception as e:
        logger.debug(f"cities.json indisponível: {e}")

    # Fallback: config.py
    try:
        from config import CITIES
        for city in CITIES:
            if city["name"].lower() == city_name.lower():
                return city["lat"], city["lon"]
    except Exception:
        pass

    return None, None


def _resolve_trade(trade: Dict, actual_temp: float) -> str:
    """Determina resultado do trade dado a temperatura real."""
    condition   = (trade.get("type") or trade.get("condition") or "ABOVE").upper()
    target      = float(trade.get("target", 0))
    unit        = (trade.get("unit") or "C").upper()

    # Converte target para Celsius para comparar com actual_temp (sempre em °C)
    if unit == "F":
        target_c = (target - 32) * 5 / 9
    else:
        target_c = target

    if condition == "ABOVE":
        return "WIN" if actual_temp > target_c else "LOSS"
    elif condition == "BELOW":
        return "WIN" if actual_temp < target_c else "LOSS"
    else:  # EXACT
        return "WIN" if abs(actual_temp - target_c) <= 0.5 else "LOSS"


def settle_all():
    """
    Liquida todos os trades OPEN cujo market_date já passou.
    Opera directamente sobre load_bankroll / save_bankroll.
    """
    data    = load_bankroll()
    history = data.get("history", [])
    balance = float(data.get("balance", 0))

    today = datetime.utcnow().date()

    open_trades = [
        t for t in history
        if t.get("result") == "OPEN"
    ]

    if not open_trades:
        logger.info("Nenhum trade aberto para liquidar.")
        return

    ready = []
    for t in open_trades:
        try:
            mdate = datetime.strptime(t["market_date"], "%Y-%m-%d").date()
            if mdate <= today:
                ready.append(t)
        except Exception:
            pass

    if not ready:
        logger.info(f"Nenhum trade pronto ({len(open_trades)} abertos, aguardando datas futuras).")
        return

    logger.info(f"Liquidando {len(ready)} trades...")

    wins   = 0
    losses = 0
    total_pnl = 0.0

    for trade in ready:
        city        = trade.get("city", "")
        date_str    = trade.get("market_date", "")
        stake       = float(trade.get("stake", 0))
        model_prob  = trade.get("model_prob")
        forecast_c  = trade.get("forecast_c")
        day_offset  = trade.get("forecast_day", 1)
        unit        = trade.get("unit", "C")
        target      = trade.get("target")

        lat = trade.get("lat")
        lon = trade.get("lon")
        if lat is None or lon is None:
            lat, lon = _get_city_coordinates(city)

        if lat is None:
            logger.warning(f"Sem coordenadas para {city} — pulando trade {trade.get('market_id')}")
            continue

        actual_temp = get_actual_temperature(lat, lon, date_str)
        if actual_temp is None:
            logger.warning(f"Temperatura real indisponível para {city} {date_str} — pulando")
            continue

        result = _resolve_trade(trade, actual_temp)

        # Calcula PnL
        if result == "WIN":
            market_price = float(trade.get("market_price", 0.5))
            shares       = int(trade.get("shares", 0))
            if shares > 0 and market_price > 0:
                gross   = shares * 1.0          # cada share vale $1 se resolve YES
                fee     = round(gross * 0.02, 4)
                pnl     = round(gross - stake - fee, 4)
            else:
                fee  = 0.0
                pnl  = round(stake * (1 / market_price - 1) * 0.98, 4) if market_price > 0 else 0.0
            wins += 1
        else:
            fee  = 0.0
            pnl  = round(-stake, 4)
            losses += 1

        balance   += pnl
        total_pnl += pnl

        # Atualiza trade no histórico (in-place)
        trade["result"]      = result
        trade["pnl"]         = pnl
        trade["fee"]         = fee
        trade["real_temp_c"] = actual_temp
        trade["exit_time"]   = datetime.utcnow().isoformat()

        logger.info(
            f"  {result}: {city} {date_str} | "
            f"actual={actual_temp:.1f}°C target={target}°{unit} | "
            f"stake=${stake:.2f} pnl=${pnl:+.2f}"
        )

        # Calibração de sigma e ML
        if forecast_c is not None:
            try:
                _calibrator.record_trade_result(
                    city=city,
                    day_offset=day_offset or 1,
                    predicted_temp=float(forecast_c),
                    actual_temp=actual_temp,
                )
                if model_prob is not None:
                    _ml_adjuster.update(
                        model_prob=float(model_prob),
                        day_offset=day_offset or 1,
                        city=city,
                        calibrator=_calibrator,
                        trade_success=(result == "WIN"),
                    )
            except Exception as e:
                logger.debug(f"Calibração: {e}")

        # Notificações Telegram
        try:
            kwargs = dict(
                city=city, market_date=date_str,
                target=target, unit=unit,
                stake=stake, pnl=pnl,
                saldo=balance,
                model_prob=model_prob,
                real_temp_c=actual_temp,
            )
            if result == "WIN":
                notificar_settlement_win(**kwargs)
            else:
                notificar_settlement_loss(**kwargs)
        except Exception as e:
            logger.debug(f"Telegram: {e}")

    data["balance"] = round(balance, 4)
    save_bankroll(data)

    resolved = wins + losses
    if resolved > 0:
        try:
            notificar_settlement_resumo(resolved, wins, losses, total_pnl, balance)
        except Exception:
            pass

    logger.info(
        f"Settlement concluído: {resolved} resolvidos "
        f"({wins}W/{losses}L) PnL ${total_pnl:+.2f} | Saldo ${balance:.2f}"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    settle_all()
