#!/usr/bin/env python3
"""
paper_execution.py — execução simulada contra o order book real da Polymarket.

Nao assina nem envia ordens. O modulo apenas busca o book CLOB publico e
simula uma compra marketable atravessando asks reais para estimar fill,
preco medio, slippage e liquidez executavel.
"""

import time
from dataclasses import dataclass
from typing import Dict, List, Optional

import requests

from config import (
    ORDERBOOK_TIMEOUT,
    PAPER_EXECUTION_REQUIRED,
    PAPER_MAX_SLIPPAGE,
    PAPER_MIN_FILL_RATIO,
)


CLOB_BOOK_URL = "https://clob.polymarket.com/book"


@dataclass
class PaperExecution:
    ok: bool
    reason: str
    side: str
    token_id: str = ""
    requested_stake: float = 0.0
    filled_cost: float = 0.0
    shares: float = 0.0
    avg_price: float = 0.0
    best_ask: Optional[float] = None
    slippage: float = 0.0
    fill_ratio: float = 0.0
    levels_used: int = 0
    book_ts: float = 0.0

    def as_trade_fields(self) -> Dict:
        return {
            "paper_execution": True,
            "paper_execution_ok": self.ok,
            "paper_execution_reason": self.reason,
            "clob_token_id": self.token_id,
            "requested_stake": round(self.requested_stake, 4),
            "filled_cost": round(self.filled_cost, 4),
            "avg_entry_price": round(self.avg_price, 4),
            "best_ask": round(self.best_ask, 4) if self.best_ask is not None else None,
            "slippage": round(self.slippage, 4),
            "fill_ratio": round(self.fill_ratio, 4),
            "book_levels_used": self.levels_used,
            "orderbook_ts": self.book_ts,
        }


def _to_float(value, default=None):
    try:
        if value in (None, ""):
            return default
        return float(value)
    except Exception:
        return default


def _book_levels(book: Dict) -> List[Dict[str, float]]:
    asks = book.get("asks") or []
    levels = []
    for raw in asks:
        price = _to_float(raw.get("price") if isinstance(raw, dict) else None)
        size = _to_float(raw.get("size") if isinstance(raw, dict) else None)
        if price is None or size is None:
            continue
        if price <= 0 or price >= 1 or size <= 0:
            continue
        levels.append({"price": price, "size": size})
    return sorted(levels, key=lambda level: level["price"])


def fetch_order_book(token_id: str) -> Dict:
    resp = requests.get(
        CLOB_BOOK_URL,
        params={"token_id": str(token_id)},
        timeout=ORDERBOOK_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def simulate_buy_from_levels(
    levels: List[Dict[str, float]],
    stake: float,
    token_id: str = "",
    side: str = "YES",
) -> PaperExecution:
    requested = max(0.0, float(stake or 0))
    if requested <= 0:
        return PaperExecution(False, "stake zero", side=side, token_id=token_id)
    if not levels:
        return PaperExecution(False, "order book sem asks", side=side, token_id=token_id, requested_stake=requested)

    remaining = requested
    filled_cost = 0.0
    shares = 0.0
    used = 0

    for level in levels:
        price = float(level["price"])
        available_shares = float(level["size"])
        max_cost = available_shares * price
        take_cost = min(remaining, max_cost)
        if take_cost <= 0:
            continue
        take_shares = take_cost / price
        filled_cost += take_cost
        shares += take_shares
        remaining -= take_cost
        used += 1
        if remaining <= 1e-9:
            break

    fill_ratio = filled_cost / requested if requested > 0 else 0.0
    avg_price = filled_cost / shares if shares > 0 else 0.0
    best_ask = levels[0]["price"]
    slippage = max(0.0, avg_price - best_ask) if avg_price else 0.0

    if fill_ratio < PAPER_MIN_FILL_RATIO:
        return PaperExecution(
            False,
            f"fill insuficiente ({fill_ratio:.1%} < {PAPER_MIN_FILL_RATIO:.1%})",
            side=side,
            token_id=token_id,
            requested_stake=requested,
            filled_cost=filled_cost,
            shares=shares,
            avg_price=avg_price,
            best_ask=best_ask,
            slippage=slippage,
            fill_ratio=fill_ratio,
            levels_used=used,
            book_ts=time.time(),
        )

    if slippage > PAPER_MAX_SLIPPAGE:
        return PaperExecution(
            False,
            f"slippage alto ({slippage:.3f} > {PAPER_MAX_SLIPPAGE:.3f})",
            side=side,
            token_id=token_id,
            requested_stake=requested,
            filled_cost=filled_cost,
            shares=shares,
            avg_price=avg_price,
            best_ask=best_ask,
            slippage=slippage,
            fill_ratio=fill_ratio,
            levels_used=used,
            book_ts=time.time(),
        )

    return PaperExecution(
        True,
        "filled",
        side=side,
        token_id=token_id,
        requested_stake=requested,
        filled_cost=filled_cost,
        shares=shares,
        avg_price=avg_price,
        best_ask=best_ask,
        slippage=slippage,
        fill_ratio=fill_ratio,
        levels_used=used,
        book_ts=time.time(),
    )


def simulate_paper_buy(market: Dict, side: str, stake: float) -> PaperExecution:
    side = str(side or "YES").upper()
    token_key = "yes_token_id" if side == "YES" else "no_token_id"
    token_id = str(market.get(token_key) or "").strip()
    if not token_id:
        reason = f"token CLOB ausente para {side}"
        return PaperExecution(not PAPER_EXECUTION_REQUIRED, reason, side=side, requested_stake=float(stake or 0))

    try:
        book = fetch_order_book(token_id)
    except Exception as exc:
        return PaperExecution(
            not PAPER_EXECUTION_REQUIRED,
            f"erro ao buscar order book: {exc}",
            side=side,
            token_id=token_id,
            requested_stake=float(stake or 0),
        )

    return simulate_buy_from_levels(_book_levels(book), stake, token_id=token_id, side=side)
