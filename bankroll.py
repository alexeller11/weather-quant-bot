#!/usr/bin/env python3
"""
BANKROLL — WEATHER QUANT
========================
Persistência com 3 camadas de segurança:

1. bankroll_override.json — correção manual (se existir, aplica e remove)
2. PostgreSQL (Railway) — fonte principal
3. bankroll.json local  — cache local
4. GitHub commit        — backup externo
"""

import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from config import START_BALANCE, CITY_DISPLAY, CITY_SLUG_NORMALIZE

BANKROLL_FILE = "bankroll.json"
OVERRIDE_FILE = "bankroll_override.json"

# ──────────────────────────────────────────────────────────────
# NORMALIZAÇÃO E CHAVES CANÔNICAS
# ──────────────────────────────────────────────────────────────


def _strip_accents(text: str) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", str(text))
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_city_slug(city_like: Any) -> str:
    """Normaliza cidade para slug estável (ex.: 'São Paulo' -> 'sao-paulo')."""
    if city_like is None:
        return ""

    text = _strip_accents(str(city_like)).strip().lower()
    text = text.replace("_", "-")
    text = text.replace(" ", "-")
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def _format_number(value: Any) -> str:
    try:
        num = float(value)
    except Exception:
        return str(value).strip()
    if num.is_integer():
        return str(int(num))
    text = f"{num:.2f}".rstrip("0").rstrip(".")
    return text


def canonical_market_base(
    city: Any,
    market_date: Any,
    condition: Any,
    target: Any,
    unit: str = "C",
    target_lo: Any = None,
    target_hi: Any = None,
) -> str:
    """Chave canônica do mercado sem lado (YES/NO)."""
    city_slug = normalize_city_slug(city)
    condition = str(condition or "").strip().upper()
    unit = str(unit or "C").strip().upper() or "C"
    market_date = str(market_date or "").strip()

    if condition == "RANGE2" and target_lo is not None and target_hi is not None:
        target_repr = f"{_format_number(target_lo)}-{_format_number(target_hi)}"
    else:
        target_repr = _format_number(target)

    return "|".join([city_slug, market_date, condition, target_repr, unit])


def _split_trade_id(value: Any) -> tuple[str, Optional[str]]:
    text = str(value or "").strip()
    if not text:
        return "", None

    for suffix in ("_YES", "_NO", "|YES", "|NO"):
        if text.endswith(suffix):
            return text[: -len(suffix)], suffix.replace("_", "").replace("|", "")

    parts = text.split("|")
    if len(parts) == 6 and parts[-1] in ("YES", "NO"):
        return "|".join(parts[:-1]), parts[-1]

    return text, None


def trade_base_key(trade: Dict[str, Any]) -> str:
    """Retorna a chave base (sem lado) de um trade."""
    if not isinstance(trade, dict):
        return ""

    for candidate in (
        trade.get("market_key"),
        trade.get("market_base"),
        trade.get("market_id"),
        trade.get("trade_id"),
    ):
        base, side = _split_trade_id(candidate)
        if base and base.count("|") >= 4:
            return base
        if base and side and base.count("|") >= 4:
            return base

    city = trade.get("city") or trade.get("city_slug") or trade.get("city_name") or ""
    market_date = trade.get("market_date") or trade.get("date") or ""
    condition = trade.get("type") or trade.get("condition") or ""
    unit = trade.get("unit") or "C"
    target = trade.get("target")
    target_lo = trade.get("target_lo")
    target_hi = trade.get("target_hi")

    if city and market_date and condition:
        return canonical_market_base(
            city=city,
            market_date=market_date,
            condition=condition,
            target=target,
            unit=unit,
            target_lo=target_lo,
            target_hi=target_hi,
        )

    for candidate in (
        trade.get("market_key"),
        trade.get("market_base"),
        trade.get("market_id"),
        trade.get("gamma_market_id"),
        trade.get("trade_id"),
    ):
        if candidate:
            return str(candidate).strip()

    return ""


def trade_unique_key(trade: Dict[str, Any]) -> str:
    """Chave do trade com lado (YES/NO), quando disponível."""
    base = trade_base_key(trade)
    side = str(trade.get("side") or "").strip().upper()

    _, parsed_side = _split_trade_id(trade.get("market_id"))
    if not side and parsed_side:
        side = parsed_side

    if side in ("YES", "NO") and base:
        return f"{base}|{side}"
    return base


def _key_variants(key: Any) -> set[str]:
    text = str(key or "").strip()
    if not text:
        return set()

    base, side = _split_trade_id(text)
    variants = {text, base}

    if base and side in ("YES", "NO"):
        variants.add(f"{base}|{side}")
        variants.add(f"{base}_{side}")

    if text.endswith("_YES"):
        variants.add(text[:-4] + "|YES")
    if text.endswith("_NO"):
        variants.add(text[:-3] + "|NO")
    if text.endswith("|YES"):
        variants.add(text[:-4] + "_YES")
    if text.endswith("|NO"):
        variants.add(text[:-3] + "_NO")

    return {v for v in variants if v}


def dedupe_history_by_market(history: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove duplicidades por mercado/side preservando a primeira ocorrência."""
    seen = set()
    out = []
    for trade in history or []:
        if not isinstance(trade, dict):
            continue
        key = trade_unique_key(trade)
        if not key:
            key = str(trade.get("market_id") or trade.get("gamma_market_id") or "")
        if not key:
            key = f"_unknown_{len(out)}"
        if key in seen:
            continue
        seen.add(key)
        out.append(trade)
    return out


def already_traded(history, market_id):
    query_variants = _key_variants(market_id)
    if not query_variants:
        return False

    for trade in history or []:
        if not isinstance(trade, dict):
            continue
        trade_variants = set()
        for candidate in (
            trade.get("market_id"),
            trade.get("gamma_market_id"),
            trade.get("market_key"),
            trade.get("market_base"),
            trade_unique_key(trade),
            trade_base_key(trade),
        ):
            trade_variants |= _key_variants(candidate)
        if query_variants & trade_variants:
            return True
    return False


# ──────────────────────────────────────────────────────────────
# POSTGRESQL
# ──────────────────────────────────────────────────────────────

def _get_db():
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        return None
    try:
        import psycopg2
        conn = psycopg2.connect(url, sslmode="require")
        return conn
    except Exception as e:
        print(f"  [db] conexão falhou: {e}")
        return None


def _ensure_table(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bankroll (
                id       SERIAL PRIMARY KEY,
                data     JSONB NOT NULL,
                saved_at TIMESTAMP DEFAULT NOW()
            )
        """)
    conn.commit()


def _load_from_db(conn):
    _ensure_table(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT data FROM bankroll ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
    return row[0] if row else None


def _save_to_db(conn, data):
    _ensure_table(conn)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO bankroll (data) VALUES (%s) RETURNING id",
            (json.dumps(data),)
        )
        row = cur.fetchone()
        if not row:
            raise Exception("INSERT não retornou id")
    conn.commit()


# ──────────────────────────────────────────────────────────────
# API PÚBLICA
# ──────────────────────────────────────────────────────────────

def initialize():
    if not os.path.exists(BANKROLL_FILE):
        data = {
            "balance": START_BALANCE,
            "start_balance": START_BALANCE,
            "history": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(BANKROLL_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)


def _coerce_bankroll_shape(data):
    if not isinstance(data, dict):
        return {
            "balance": START_BALANCE,
            "start_balance": START_BALANCE,
            "history": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    if "balance" not in data:
        data["balance"] = START_BALANCE
    if "start_balance" not in data:
        data["start_balance"] = START_BALANCE
    if "history" not in data or not isinstance(data.get("history"), list):
        data["history"] = []
    if "created_at" not in data:
        data["created_at"] = datetime.now(timezone.utc).isoformat()
    return data


def load_bankroll():
    """
    Cascata:
    1. bankroll_override.json — se existir, salva no DB e remove o arquivo
    2. PostgreSQL
    3. bankroll.json local
    4. valor inicial
    """
    # ── OVERRIDE MANUAL ──────────────────────────────────────
    if os.path.exists(OVERRIDE_FILE) and os.environ.get("APPLY_BANKROLL_OVERRIDE", "0") == "1":
        try:
            with open(OVERRIDE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            data = _coerce_bankroll_shape(data)
            print(f"  [override] aplicando bankroll_override.json — saldo ${data.get('balance',0):.2f}")
            # Salva no PostgreSQL e local
            _apply_override(data)
            os.remove(OVERRIDE_FILE)
            print("  [override] concluído e arquivo removido")
            return data
        except Exception as e:
            print(f"  [override] erro: {e}")

    # ── POSTGRESQL ───────────────────────────────────────────
    conn = _get_db()
    if conn:
        try:
            data = _load_from_db(conn)
            conn.close()
            if data:
                data = _coerce_bankroll_shape(data)
                with open(BANKROLL_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
                print("  [db] bankroll carregado do PostgreSQL")
                return data
        except Exception as e:
            print(f"  [db] load falhou, usando local: {e}")
            try:
                conn.close()
            except Exception:
                pass

    # ── LOCAL ────────────────────────────────────────────────
    initialize()
    with open(BANKROLL_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return _coerce_bankroll_shape(data)


def _apply_override(data):
    """Salva override no PostgreSQL e local."""
    data = _coerce_bankroll_shape(data)

    with open(BANKROLL_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    conn = _get_db()
    if conn:
        try:
            _save_to_db(conn, data)
            conn.close()
            print(f"  [override] salvo no PostgreSQL — saldo ${data.get('balance',0):.2f}")
        except Exception as e:
            print(f"  [override] PostgreSQL falhou: {e}")
            try:
                conn.close()
            except Exception:
                pass


def save_bankroll(data):
    data = _coerce_bankroll_shape(data)

    with open(BANKROLL_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    conn = _get_db()
    if conn:
        try:
            _save_to_db(conn, data)
            conn.close()
            print(f"  [db] bankroll salvo — saldo: ${data.get('balance', 0):.2f}")
        except Exception as e:
            print(f"  [db] save falhou: {e}")
            try:
                conn.close()
            except Exception:
                pass

    try:
        from github_sync import commit_bankroll
        commit_bankroll(data)
    except Exception as e:
        print(f"  [github] indisponível: {e}")


# ──────────────────────────────────────────────────────────────
# FUNÇÕES DE TRADE
# ──────────────────────────────────────────────────────────────

def get_open_trades():
    data = load_bankroll()
    return [t for t in data.get("history", []) if t.get("result") == "OPEN"]


def record_trade(trade):
    data = load_bankroll()
    stake = float(trade.get("stake", 0))
    data["balance"] = round(float(data.get("balance", 0)) - stake, 4)
    data.setdefault("history", []).append(trade)
    save_bankroll(data)


# ──────────────────────────────────────────────────────────────
# UTILITÁRIOS
# ──────────────────────────────────────────────────────────────

def normalize_city(city_slug):
    if not city_slug:
        return "Unknown"
    normalized = CITY_DISPLAY.get(city_slug)
    if normalized:
        return normalized
    return city_slug.replace("-", " ").replace("_", " ").title()


def force_close_open_trades(market_date_str):
    data = load_bankroll()
    fechados = 0
    for trade in data["history"]:
        if trade.get("result") != "OPEN":
            continue
        mdate = trade.get("market_date", "")
        if mdate <= market_date_str:
            stake = float(trade.get("stake", 0))
            trade["result"]    = "LOSS"
            trade["pnl"]       = round(-stake, 2)
            trade["fee"]       = 0.0
            trade["exit_time"] = datetime.utcnow().isoformat()
            print(f"  Fechando LOSS: {trade.get('city')} {mdate} ${stake:.2f}")
            fechados += 1
    if fechados > 0:
        save_bankroll(data)
        print(f"  {fechados} trades fechados. Saldo: ${data['balance']:.2f}")
    else:
        print("  Nenhum trade encontrado para fechar.")
    return fechados


def reset_bankroll(starting_balance=None):
    balance = starting_balance if starting_balance is not None else START_BALANCE
    save_bankroll({
        "balance":       balance,
        "start_balance": balance,
        "history":       [],
        "created_at":    datetime.now(timezone.utc).isoformat(),
    })
    print(f"Bankroll resetado. Saldo inicial: ${balance:.2f}")
