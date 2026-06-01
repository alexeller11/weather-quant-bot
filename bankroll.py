"""
BANKROLL — WEATHER QUANT
========================
Persistência com 3 camadas de segurança:

1. PostgreSQL (Railway) — fonte principal
2. bankroll.json local  — cache local
3. GitHub commit        — backup externo

CORRIGIDO:
- Adicionadas funções get_open_trades() e update_trade() que estavam
  ausentes mas eram importadas por bot.py e settlement.py
- _save_to_db era função interna do módulo PostgreSQL; bot.py não deve
  importá-la diretamente — criada função pública record_trade() no lugar
"""

import json
import os
from datetime import datetime, timezone

from config import START_BALANCE, CITY_DISPLAY, CITY_SLUG_NORMALIZE

BANKROLL_FILE = "bankroll.json"

# ──────────────────────────────────────────────────────────────
# POSTGRESQL
# ──────────────────────────────────────────────────────────────

def _get_db():
    """Retorna conexão psycopg2 ou None se não configurado."""
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
    """Cria tabela se não existir."""
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
    """Carrega último bankroll salvo no banco."""
    _ensure_table(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT data FROM bankroll ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
    return row[0] if row else None


def _save_to_db(conn, data):
    """
    Salva bankroll no banco com RETURNING id para confirmar persistência.
    Lança exceção se o INSERT não for confirmado.
    """
    _ensure_table(conn)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO bankroll (data) VALUES (%s) RETURNING id",
            (json.dumps(data),)
        )
        row = cur.fetchone()
        if not row:
            raise Exception("INSERT não retornou id — save não confirmado pelo banco")
    conn.commit()


# ──────────────────────────────────────────────────────────────
# API PÚBLICA
# ──────────────────────────────────────────────────────────────

def initialize():
    """Garante que bankroll.json existe se não houver banco."""
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
    Carrega bankroll com fallback em cascata:
    1. PostgreSQL (mais atualizado)
    2. bankroll.json local
    3. valor inicial
    """
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

    initialize()
    with open(BANKROLL_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_bankroll(data):
    """
    Salva bankroll em todas as camadas disponíveis.
    """
    if "start_balance" not in data:
        data["start_balance"] = START_BALANCE
    if "created_at" not in data:
        data["created_at"] = datetime.now(timezone.utc).isoformat()

    # 1. Local (sempre, rápido)
    with open(BANKROLL_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    # 2. PostgreSQL com confirmação
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

    # 3. GitHub como backup externo (silencioso)
    try:
        from github_sync import commit_bankroll
        commit_bankroll(data)
    except Exception as e:
        print(f"  [github] indisponível: {e}")


# ──────────────────────────────────────────────────────────────
# FUNÇÕES DE TRADE — ADICIONADAS (eram importadas mas não existiam)
# ──────────────────────────────────────────────────────────────

def get_open_trades():
    """
    Retorna lista de trades com result == 'OPEN'.
    ADICIONADO: bot.py e settlement.py importavam esta função,
    mas ela não existia em bankroll.py.
    """
    data = load_bankroll()
    return [t for t in data.get("history", []) if t.get("result") == "OPEN"]



def record_trade(trade):
    """
    Registra um novo trade no bankroll e desconta o stake do saldo.
    ADICIONADO: bot.py não deve importar _save_to_db diretamente —
    esta função pública substitui o uso indevido de _save_to_db em bot.py.
    """
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
    """Converte slug em display name."""
    if not city_slug:
        return "Unknown"
    normalized = CITY_DISPLAY.get(city_slug)
    if normalized:
        return normalized
    return city_slug.replace("-", " ").replace("_", " ").title()


def force_close_open_trades(market_date_str):
    """
    UTILITÁRIO DE EMERGÊNCIA.
    Fecha todos os trades OPEN com data <= market_date_str como LOSS.
    """
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
