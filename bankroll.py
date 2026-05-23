"""
BANKROLL — WEATHER QUANT
========================
Persistência com 3 camadas de segurança:

1. PostgreSQL (Railway) — fonte principal, persiste para sempre
2. bankroll.json local  — cache local para leitura rápida
3. GitHub commit        — backup externo a cada save

Se o PostgreSQL não estiver configurado, cai para JSON local + GitHub.
"""

import json
import os

from config import START_BALANCE, CITY_DISPLAY, CITY_SLUG_NORMALIZE

BANKROLL_FILE = "bankroll.json"

# ──────────────────────────────────────────────────────────────
# POSTGRESQL — conexão lazy (só conecta se DATABASE_URL existir)
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
                id      SERIAL PRIMARY KEY,
                data    JSONB NOT NULL,
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
    if row:
        return row[0]  # psycopg2 retorna JSONB como dict direto
    return None


def _save_to_db(conn, data):
    """Salva bankroll no banco (INSERT — mantém histórico de snapshots)."""
    _ensure_table(conn)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO bankroll (data) VALUES (%s)",
            (json.dumps(data),)
        )
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
            "created_at": ""
        }
        with open(BANKROLL_FILE, "w") as f:
            json.dump(data, f, indent=4)


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
                # Mantém cache local sincronizado
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

    # Fallback: arquivo local
    initialize()
    with open(BANKROLL_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_bankroll(data):
    """
    Salva bankroll em todas as camadas disponíveis:
    1. PostgreSQL
    2. bankroll.json local
    3. GitHub commit (assíncrono)
    """
    # Garantir campos essenciais
    if "start_balance" not in data:
        data["start_balance"] = START_BALANCE
    if "created_at" not in data:
        from datetime import datetime, timezone
        data["created_at"] = datetime.now(timezone.utc).isoformat()

    # 1. Salva local sempre (rápido)
    with open(BANKROLL_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    # 2. Salva no PostgreSQL
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


def reset_bankroll(starting_balance=None):
    from datetime import datetime, timezone
    balance = starting_balance if starting_balance is not None else START_BALANCE
    save_bankroll({
        "balance": balance,
        "start_balance": balance,
        "history": [],
        "created_at": datetime.now(timezone.utc).isoformat()
    })
    print(f"Bankroll resetado. Saldo inicial: ${balance:.2f}")


def normalize_city(city_slug):
    key  = city_slug.lower().replace(" ", "-")
    slug = CITY_SLUG_NORMALIZE.get(key) or CITY_SLUG_NORMALIZE.get(
        city_slug.lower().replace("-", " ").strip()
    )
    if slug:
        return CITY_DISPLAY[slug]
    return city_slug.title()


def already_traded(history, market_id):
    for trade in history:
        if trade.get("market_id") == market_id:
            return True
    return False
