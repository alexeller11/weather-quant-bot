#!/usr/bin/env python3
"""
settlement.py — Liquidação de trades

CORRIGIDO v5: suporte ao tipo range2.
CORREÇÕES (auditoria): timezone, atomicidade, payout, fee, ML.

AUDITORIA SENIOR:
- settle_trade() (legacy) marcado como DEPRECATED. Operava fora de lock
  e podia causar race condition. Use settle_all().
"""

import logging
import json
import os
import warnings
import requests
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from sigma_calibrator import SigmaCalibrator
from ml_adjuster import MLProbabilityAdjuster
from model import get_calibrator, get_ml_adjuster, delta_to_celsius
from bankroll import (
    load_bankroll,
    save_bankroll,
    get_open_trades,
    atomic_update,
    trade_unique_key,
    normalize_city_slug,
)
from forecast import city_today
from risk import FEE_RATE

logger = logging.getLogger("settlement")

_calibrator  = get_calibrator()
_ml_adjuster = get_ml_adjuster()


def get_actual_temperature(lat: float, lon: float, date: str) -> Optional[float]:
    """
    Máxima do DIA LOCAL `date` na coordenada.
    1) archive-api (ERA5) com timezone=auto;
    2) fallback: forecast-api com past_days=5.
    """
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
        days  = data.get("daily", {}).get("time", []) or []
        temps = data.get("daily", {}).get("temperature_2m_max", []) or []
        for d, t in zip(days, temps):
            if d == date and t is not None:
                return float(t)
        raise ValueError("Temperatura ausente no archive")
    except Exception as e:
        logger.warning(f"archive-api indisponível para ({lat},{lon}) em {date}: {e}")

    try:
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude":  lat,
            "longitude": lon,
            "daily":     "temperature_2m_max",
            "timezone":  "auto",
            "past_days": 5,
            "forecast_days": 1,
        }
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        days  = data.get("daily", {}).get("time", []) or []
        temps = data.get("daily", {}).get("temperature_2m_max", []) or []
        for d, t in zip(days, temps):
            if d == date and t is not None:
                logger.info(f"Temperatura real via forecast-api (past_days): {date} = {t}°C")
                return float(t)
        raise ValueError(f"Data {date} fora da janela past_days")
    except Exception as e:
        logger.error(f"Temperatura real indisponível para ({lat},{lon}) em {date}: {e}")
        return None


def _get_city_coordinates(city_name: str) -> tuple:
    try:
        cities_path = os.path.join(os.path.dirname(__file__), "cities.json")
        with open(cities_path, "r") as f:
            cities = json.load(f)
        for city in cities:
            if city["name"].lower() == city_name.lower():
                return city["lat"], city["lon"]
    except Exception as e:
        logger.warning(f"cities.json: {e}")

    try:
        from config import CITIES
        for city in CITIES:
            if city["name"].lower() == city_name.lower():
                return city["lat"], city["lon"]
    except Exception:
        pass

    logger.error(f"Coordenadas não encontradas para: {city_name}")
    return None, None


def _trade_is_ready(trade: Dict) -> bool:
    market_date_str = trade.get("market_date", "")
    if not market_date_str:
        return False
    try:
        market_date = datetime.strptime(market_date_str, "%Y-%m-%d").date()
        slug = normalize_city_slug(trade.get("city", ""))
        local_today = datetime.strptime(city_today(slug), "%Y-%m-%d").date()
        return market_date < local_today
    except Exception:
        return False


def _entry_hour_utc(trade: Dict) -> int:
    raw = trade.get("entry_time") or ""
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).hour
    except Exception:
        return datetime.now(timezone.utc).hour


def _compute_settlement(trade: Dict, actual_temp_c: float) -> Dict:
    """
    Calcula o trade liquidado (puro: sem I/O, sem efeitos colaterais).
    Retorna o dict do trade com result/pnl/fee/real_temp_c/exit_time e
    o crédito de settlement em trade["_settlement_credit"] (interno).
    """
    condition   = (trade.get("type") or "ABOVE").upper()
    target      = float(trade.get("target", 0))
    unit        = (trade.get("unit") or "C").upper()
    stake       = float(trade.get("stake", 0))
    market_price = float(trade.get("market_price", 0))
    entry_price  = float(trade.get("entry_price") or market_price)
    side         = trade.get("side", "YES").upper()
    target_lo   = trade.get("target_lo")
    target_hi   = trade.get("target_hi")

    if unit == "F":
        target_c = (target - 32) * 5 / 9
        lo_c = ((target_lo - 32) * 5 / 9) if target_lo is not None else None
        hi_c = ((target_hi - 32) * 5 / 9) if target_hi is not None else None
    else:
        target_c = target
        lo_c = target_lo
        hi_c = target_hi

    half_exact  = delta_to_celsius(0.5, unit)
    half_range2 = delta_to_celsius(1.0, unit)

    if condition == "ABOVE":
        won = actual_temp_c >= target_c
    elif condition == "BELOW":
        won = actual_temp_c <= target_c
    elif condition == "RANGE2":
        if lo_c is not None and hi_c is not None:
            if lo_c > hi_c:
                lo_c, hi_c = hi_c, lo_c
            won = lo_c <= actual_temp_c <= hi_c
        else:
            won = abs(actual_temp_c - target_c) <= half_range2
    else:  # EXACT
        won = abs(actual_temp_c - target_c) <= half_exact

    if side == "NO":
        won = not won

    if entry_price <= 0 or entry_price >= 1:
        if side == "NO":
            entry_price = round(1.0 - market_price, 4)
        else:
            entry_price = market_price

    shares = trade.get("shares")

    if won:
        if shares:
            gross = float(shares) * 1.0
        elif entry_price > 0:
            gross = stake / entry_price
        else:
            gross = 0.0
        if gross > 0:
            fee   = round(gross * FEE_RATE, 4)
            pnl   = round(gross - stake - fee, 4)
            settlement_credit = round(gross - fee, 4)
        else:
            fee = 0.0
            pnl = 0.0
            settlement_credit = 0.0
    else:
        fee = 0.0
        pnl = round(-stake, 4)
        settlement_credit = 0.0

    settled = dict(trade)
    settled["result"]      = "WIN" if won else "LOSS"
    settled["pnl"]         = pnl
    settled["fee"]         = fee
    settled["real_temp_c"] = actual_temp_c
    settled["exit_time"]   = datetime.now(timezone.utc).isoformat()
    settled["_settlement_credit"] = settlement_credit
    return settled


def settle_trade(trade: Dict, bankroll_data: Dict) -> Dict:
    """
    DEPRECATED — use settle_all() em vez desta função.

    Esta função carrega e modifica o bankroll FORA de lock, podendo
    causar race condition quando chamada por subprocessos (Telegram,
    scripts manuais) concorrentemente com o loop principal.

    Mantida apenas para compatibilidade retroativa. Será removida
    numa versão futura.
    """
    warnings.warn(
        "settle_trade() esta deprecated e opera fora de lock. "
        "Use settle_all() para liquidacao segura e atomica.",
        DeprecationWarning,
        stacklevel=2,
    )
    logger.error(
        "settle_trade() DEPRECATED chamada detectada. "
        "Migre para settle_all(). Abortando para evitar race condition."
    )
    # Retorna o trade sem alterar para evitar race condition silenciosa.
    return trade


def settle_all():
    # 1) Leitura SEM lock para descobrir o que está pronto.
    snapshot   = load_bankroll()
    history    = snapshot.get("history", [])
    open_trades = [t for t in history if t.get("result") == "OPEN"]
    ready       = [t for t in open_trades if _trade_is_ready(t)]

    if not ready:
        logger.info(f"Settlement: {len(open_trades)} abertos, nenhum pronto.")
        return

    logger.info(f"Settlement: liquidando {len(ready)} de {len(open_trades)} abertos")

    # 2) Busca temperaturas FORA do lock (chamadas de rede lentas).
    temps: Dict[Tuple[str, str], Optional[float]] = {}
    for t in ready:
        city = t.get("city", "")
        mdate = t.get("market_date", "")
        key = (city.lower(), mdate)
        if key in temps:
            continue
        lat = t.get("lat")
        lon = t.get("lon")
        if lat is None or lon is None:
            lat, lon = _get_city_coordinates(city)
        if lat is None:
            temps[key] = None
            continue
        temps[key] = get_actual_temperature(lat, lon, mdate)

    # 3) Aplica TUDO numa única seção crítica (atomic_update).
    settled_trades: List[Dict] = []
    summary = {"wins": 0, "losses": 0, "total_pnl": 0.0, "saldo": 0.0}

    def _mutator(data):
        hist = data.get("history", [])
        changed = False
        for i, tr in enumerate(hist):
            if tr.get("result") != "OPEN" or not _trade_is_ready(tr):
                continue
            key = ((tr.get("city", "") or "").lower(), tr.get("market_date", ""))
            actual = temps.get(key)
            if actual is None:
                continue
            settled = _compute_settlement(tr, actual)
            credit = settled.pop("_settlement_credit", 0.0)
            data["balance"] = round(float(data.get("balance", 0)) + credit, 4)
            hist[i] = settled
            changed = True
            settled_trades.append(settled)
            if settled["result"] == "WIN":
                summary["wins"] += 1
            else:
                summary["losses"] += 1
            summary["total_pnl"] += float(settled.get("pnl", 0))
        if changed:
            data["history"] = hist
            summary["saldo"] = float(data.get("balance", 0))
        return changed

    atomic_update(_mutator)

    if not settled_trades:
        logger.info("Settlement: nada liquidado (sem temperatura ou já liquidado).")
        return

    logger.info(
        f"Settlement: {summary['wins']}W/{summary['losses']}L "
        f"PnL={summary['total_pnl']:+.2f} Saldo=${summary['saldo']:.2f}"
    )

    # 4) Efeitos colaterais SOMENTE APÓS persistir o bankroll.
    for settled in settled_trades:
        city        = settled.get("city", "")
        market_date = settled.get("market_date", "")
        condition   = (settled.get("type") or "ABOVE").upper()
        target      = float(settled.get("target", 0))
        unit        = (settled.get("unit") or "C").upper()
        stake       = float(settled.get("stake", 0))
        model_prob  = float(settled.get("model_prob") or 0.5)
        forecast_c  = settled.get("forecast_c")
        day_offset  = settled.get("forecast_day", 1)
        won         = settled.get("result") == "WIN"
        pnl         = float(settled.get("pnl", 0))
        actual_temp_c = settled.get("real_temp_c")

        logger.info(
            f"{'WIN' if won else 'LOSS'}: {city} {condition} {target}°{unit} "
            f"real={actual_temp_c:.1f}C PnL={pnl:+.2f}"
        )

        if forecast_c is not None and actual_temp_c is not None:
            try:
                _calibrator.record_trade_result(
                    city=city, day_offset=day_offset,
                    predicted_temp=float(forecast_c),
                    actual_temp=float(actual_temp_c),
                    condition=condition,
                    market_date=market_date,
                )
                _ml_adjuster.update(
                    model_prob=model_prob, day_offset=day_offset,
                    city=city, calibrator=_calibrator, trade_success=won,
                    hour_utc=_entry_hour_utc(settled),
                )
            except Exception as e:
                logger.warning(f"Calibração: {e}")

        try:
            if won:
                from notificador import notificar_settlement_win
                notificar_settlement_win(
                    city=city, market_date=market_date, target=target, unit=unit,
                    stake=stake, pnl=pnl, saldo=summary["saldo"],
                    model_prob=model_prob, real_temp_c=actual_temp_c,
                )
            else:
                from notificador import notificar_settlement_loss
                notificar_settlement_loss(
                    city=city, market_date=market_date, target=target, unit=unit,
                    stake=stake, pnl=pnl, saldo=summary["saldo"],
                    model_prob=model_prob, real_temp_c=actual_temp_c,
                )
        except Exception as e:
            logger.warning(f"Telegram settlement: {e}")

    if summary["wins"] + summary["losses"] > 0:
        try:
            from notificador import notificar_settlement_resumo
            notificar_settlement_resumo(
                total_resolved=summary["wins"] + summary["losses"],
                wins=summary["wins"], losses=summary["losses"],
                total_pnl=summary["total_pnl"], saldo=summary["saldo"],
            )
        except Exception as e:
            logger.warning(f"Telegram resumo: {e}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    settle_all()
