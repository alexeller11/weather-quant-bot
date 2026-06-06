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
from datetime import datetime, timezone

from config import START_BALANCE, CITY_DISPLAY, CITY_SLUG_NORMALIZE

BANKROLL_FILE = "bankroll.json"
OVERRIDE_FILE = "bankroll_override.json"

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


def load_bankroll():
    """
    Cascata:
    1. bankroll_override.json — se existir, salva no DB e remove o arquivo
    2. PostgreSQL
    3. bankroll.json local
    4. valor inicial
    """
    # ── OVERRIDE MANUAL ──────────────────────────────────────
    if os.path.exists(OVERRIDE_FILE):
        try:
            with open(OVERRIDE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
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
        return json.load(f)


def _apply_override(data):
    """Salva override no PostgreSQL e local."""
    if "start_balance" not in data:
        data["start_balance"] = START_BALANCE
    if "created_at" not in data:
        data["created_at"] = datetime.now(timezone.utc).isoformat()

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
    if "start_balance" not in data:
        data["start_balance"] = START_BALANCE
    if "created_at" not in data:
        data["created_at"] = datetime.now(timezone.utc).isoformat()

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

def already_traded(history, market_id):
    return any(t.get("market_id") == market_id for t in history)


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
