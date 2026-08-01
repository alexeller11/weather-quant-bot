#!/usr/bin/env python3
"""
BANKROLL — WEATHER QUANT
========================
Persistência com camadas de segurança:

1. bankroll_override.json — correção manual
2. PostgreSQL (Railway) — fonte principal
3. bankroll.json local  — cache local
4. GitHub commit        — backup externo

AUDITORIA SENIOR:
- _save_to_db agora prune linhas antigas (mantendo as 100 mais recentes).
  Antes cada save_bankroll fazia INSERT sem DELETE, crescendo infinitamente.
- normalize_city corrigida: fazia lookup com slug ('new-york') mas
  CITY_DISPLAY tem chaves com espaco ('new york') -- o dict era codigo morto.
"""

import json
import logging
import os
import re
import threading
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional

from config import START_BALANCE, CITY_DISPLAY, CITY_SLUG_NORMALIZE

logger = logging.getLogger(__name__)

BANKROLL_FILE = "bankroll.json"
OVERRIDE_FILE = "bankroll_override.json"
LOCK_FILE = "bankroll.lock"

_PG_ADVISORY_KEY = 815471001
_BANKROLL_PRUNE_KEEP = 100  # linhas mais recentes a manter na tabela bankroll

_THREAD_LOCK = threading.RLock()
_LOCK_DEPTH = 0
_LOCK_FD = None

# ── File-lock compatibilidade multi-plataforma ────────────────────
try:
    import fcntl
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False

try:
    import msvcrt
    _HAS_MSVCRT = True
except ImportError:
    _HAS_MSVCRT = False

_LOCK_WARNED = False  # para logar uma única vez se nenhum lock disponível

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


def _split_trade_id(value: Any) -> tuple:
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


def _key_variants(key: Any, include_base: bool = True) -> set:
    """
    Variantes textuais de uma chave de trade.

    include_base=False omite a chave SEM lado. Isso importa: com a base
    incluída em ambos os conjuntos, already_traded("X_YES") casava com um
    trade "X_NO" pela interseção em "X" — ou seja, negociar um lado
    bloqueava o outro e o gate por lado de bot.py era código morto.
    """
    text = str(key or "").strip()
    if not text:
        return set()

    base, side = _split_trade_id(text)
    variants = {text}
    if include_base and base:
        variants.add(base)

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


def trade_side(trade: Dict[str, Any]) -> Optional[str]:
    """Lado do trade (YES/NO), inferido do campo ou do market_id."""
    side = str(trade.get("side") or "").strip().upper()
    if side in ("YES", "NO"):
        return side
    _, parsed = _split_trade_id(trade.get("market_id"))
    return parsed if parsed in ("YES", "NO") else None


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
    """
    True se ESTE mercado E ESTE LADO já foram negociados.

    Quando `market_id` traz o lado (sufixo _YES/_NO ou |YES/|NO), a
    comparação é feita por lado: negociar o NO de um mercado não bloqueia
    mais o YES do mesmo mercado. Sem lado no argumento, mantém o
    comportamento antigo (casa qualquer lado).
    """
    _, query_side = _split_trade_id(market_id)
    sided = query_side in ("YES", "NO")

    query_variants = _key_variants(market_id)
    if not query_variants:
        return False

    for trade in history or []:
        if not isinstance(trade, dict):
            continue

        # Filtra por lado ANTES de comparar chaves. Trades legados sem
        # `side` identificável não são filtrados (bloqueiam os dois lados,
        # que é o comportamento conservador).
        if sided and trade_side(trade) not in (None, query_side):
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
# LOCKS (thread + processo)
# ──────────────────────────────────────────────────────────────

@contextmanager
def _process_lock():
    global _LOCK_DEPTH, _LOCK_FD, _LOCK_WARNED
    lock_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), LOCK_FILE)
    with _THREAD_LOCK:
        acquired_here = False
        if _LOCK_DEPTH == 0:
            try:
                _LOCK_FD = open(lock_path, "a+")
                try:
                    if _HAS_FCNTL:
                        # POSIX: flock block até você pegar (LOCK_EX).
                        fcntl.flock(_LOCK_FD.fileno(), fcntl.LOCK_EX)
                    elif _HAS_MSVCRT:
                        # AUDITORIA bug #25: antes era LK_NBLCK
                        # (try-and-give-up) — em deploy Windows multi-
                        # processo isso cai no except e operava SEM lock
                        # de ficheiro (só thread-lock). Agora bloqueamos
                        # com busy-retry (LK_NBLCK + sleep) até 30 s.
                        import time as _time
                        deadline = _time.time() + 30.0
                        _LOCK_FD.seek(0)
                        while True:
                            try:
                                msvcrt.locking(_LOCK_FD.fileno(), msvcrt.LK_NBLCK, 1)
                                break
                            except OSError:
                                if _time.time() >= deadline:
                                    raise
                                _time.sleep(0.05)
                    else:
                        if not _LOCK_WARNED:
                            logger.warning(
                                "Nenhum file-lock disponível (fcntl/msvcrt). "
                                "Usando apenas thread-lock — NÃO rode processos concorrentes."
                            )
                            _LOCK_WARNED = True
                except Exception:
                    if not _LOCK_WARNED:
                        logger.warning("File-lock falhou — usando apenas thread-lock.")
                        _LOCK_WARNED = True
                acquired_here = True
            except Exception:
                _LOCK_FD = None
        _LOCK_DEPTH += 1
        try:
            yield
        finally:
            _LOCK_DEPTH -= 1
            if _LOCK_DEPTH == 0 and _LOCK_FD is not None:
                try:
                    if _HAS_FCNTL:
                        fcntl.flock(_LOCK_FD.fileno(), fcntl.LOCK_UN)
                    elif _HAS_MSVCRT:
                        _LOCK_FD.seek(0)
                        msvcrt.locking(_LOCK_FD.fileno(), msvcrt.LK_UNLCK, 1)
                except Exception:
                    pass
                try:
                    _LOCK_FD.close()
                except Exception:
                    pass
                _LOCK_FD = None


@contextmanager
def bankroll_lock():
    with _process_lock():
        yield


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
        logger.warning(f"  [db] conexão falhou: {e}")
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
    """
    INSERT serializado por advisory lock transacional.
    Apos o INSERT, prune linhas antigas mantendo apenas as
    _BANKROLL_PRUNE_KEEP mais recentes (antes crescia indefinidamente).
    """
    _ensure_table(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (_PG_ADVISORY_KEY,))
        cur.execute(
            "INSERT INTO bankroll (data) VALUES (%s) RETURNING id",
            (json.dumps(data),)
        )
        row = cur.fetchone()
        if not row:
            raise Exception("INSERT não retornou id")
        # Prune: apaga linhas fora das N mais recentes
        cur.execute("""
            DELETE FROM bankroll
            WHERE id NOT IN (
                SELECT id FROM bankroll ORDER BY id DESC LIMIT %s
            )
        """, (_BANKROLL_PRUNE_KEEP,))
    conn.commit()


# ──────────────────────────────────────────────────────────────
# API PÚBLICA
# ──────────────────────────────────────────────────────────────

def _new_bankroll() -> Dict[str, Any]:
    return {
        "balance": START_BALANCE,
        "start_balance": START_BALANCE,
        "history": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "seq": 0,
    }


def initialize():
    if not os.path.exists(BANKROLL_FILE):
        with open(BANKROLL_FILE, "w", encoding="utf-8") as f:
            json.dump(_new_bankroll(), f, indent=4, ensure_ascii=False)


def _coerce_bankroll_shape(data):
    if not isinstance(data, dict):
        return _new_bankroll()

    if "balance" not in data:
        data["balance"] = START_BALANCE
    if "start_balance" not in data:
        data["start_balance"] = START_BALANCE
    if "history" not in data or not isinstance(data.get("history"), list):
        data["history"] = []
    if "created_at" not in data:
        data["created_at"] = datetime.now(timezone.utc).isoformat()
    if "seq" not in data or not isinstance(data.get("seq"), int):
        data["seq"] = 0
    return data


def _read_local() -> Optional[Dict[str, Any]]:
    if not os.path.exists(BANKROLL_FILE):
        return None
    try:
        with open(BANKROLL_FILE, "r", encoding="utf-8") as f:
            return _coerce_bankroll_shape(json.load(f))
    except Exception as e:
        logger.warning(f"  [local] bankroll.json ilegível: {e}")
        return None


def _write_local(data) -> None:
    tmp = BANKROLL_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, BANKROLL_FILE)


def _load_freshest_unlocked() -> Dict[str, Any]:
    db_data = None
    conn = _get_db()
    if conn:
        try:
            raw = _load_from_db(conn)
            if raw:
                db_data = _coerce_bankroll_shape(raw)
        except Exception as e:
            logger.warning(f"  [db] load falhou: {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass

    local_data = _read_local()

    if db_data is not None and local_data is not None:
        if int(local_data.get("seq", 0)) > int(db_data.get("seq", 0)):
            logger.info(
                f"[sync] local seq={local_data.get('seq')} > "
                f"db seq={db_data.get('seq')} — usando local (anti-rollback)"
            )
            return local_data
        return db_data
    if db_data is not None:
        return db_data
    if local_data is not None:
        return local_data

    initialize()
    return _read_local() or _new_bankroll()


def load_bankroll():
    with bankroll_lock():
        if os.path.exists(OVERRIDE_FILE) and os.environ.get("APPLY_BANKROLL_OVERRIDE", "0") == "1":
            try:
                with open(OVERRIDE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data = _coerce_bankroll_shape(data)
                current = _load_freshest_unlocked()
                data["seq"] = int(current.get("seq", 0)) + 1
                logger.info(f"  [override] aplicando bankroll_override.json — saldo ${data.get('balance',0):.2f}")
                _persist_unlocked(data)
                os.remove(OVERRIDE_FILE)
                logger.info("  [override] concluído e arquivo removido")
                return data
            except Exception as e:
                logger.warning(f"  [override] erro: {e}")

        data = _load_freshest_unlocked()
        try:
            _write_local(data)
        except Exception as e:
            logger.warning(f"  [local] cache falhou: {e}")
        return data


def _persist_unlocked(data) -> None:
    """
    Persistência Robusta (v5.7):
    O PostgreSQL é a fonte da verdade. O bankroll.json é apenas um cache de leitura.
    """
    data = _coerce_bankroll_shape(data)

    # 1. PostgreSQL (Prioridade Máxima)
    conn = _get_db()
    db_success = False
    if conn:
        try:
            _save_to_db(conn, data)
            logger.info(f"  [db] bankroll salvo — saldo: ${data.get('balance', 0):.2f} seq={data.get('seq')}")
            db_success = True
        except Exception as e:
            logger.error(f"CRÍTICO: Falha ao salvar no PostgreSQL: {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass
    
    # 2. Local (Cache de Fallback)
    try:
        _write_local(data)
    except Exception as e:
        logger.warning(f"  [local] cache falhou: {e}")

    if not db_success:
        logger.warning("Bankroll persistido APENAS localmente. Verifique o DATABASE_URL.")

    # 3. GitHub (Backup terciário)
    try:
        from github_sync import commit_bankroll
        commit_bankroll(data)
    except Exception as e:
        logger.info(f"  [github] indisponível: {e}")


def save_bankroll(data):
    with bankroll_lock():
        data = _coerce_bankroll_shape(data)
        data["seq"] = int(data.get("seq", 0)) + 1
        data["saved_at"] = datetime.now(timezone.utc).isoformat()
        _persist_unlocked(data)


def atomic_update(mutator: Callable[[Dict[str, Any]], Any]) -> Dict[str, Any]:
    with bankroll_lock():
        data = _load_freshest_unlocked()
        result = mutator(data)
        if result is False:
            return data
        data = _coerce_bankroll_shape(data)
        data["seq"] = int(data.get("seq", 0)) + 1
        data["saved_at"] = datetime.now(timezone.utc).isoformat()
        _persist_unlocked(data)
        return data


# ──────────────────────────────────────────────────────────────
# FUNÇÕES DE TRADE
# ──────────────────────────────────────────────────────────────

def get_open_trades():
    data = load_bankroll()
    return [t for t in data.get("history", []) if t.get("result") == "OPEN"]


def record_trade(trade) -> bool:
    outcome = {"recorded": False}

    def _mutator(data):
        history = data.setdefault("history", [])
        new_key = trade_unique_key(trade)
        if new_key:
            for existing in history:
                if trade_unique_key(existing) == new_key:
                    logger.info(f"  [bankroll] trade duplicado ignorado: {new_key}")
                    return False
        stake = float(trade.get("stake", 0))
        if stake < 0:
            return False
        data["balance"] = round(float(data.get("balance", 0)) - stake, 4)
        history.append(trade)
        outcome["recorded"] = True
        return True

    atomic_update(_mutator)
    return outcome["recorded"]


# ──────────────────────────────────────────────────────────────
# UTILITÁRIOS
# ──────────────────────────────────────────────────────────────

def normalize_city(city_slug):
    """
    Converte slug de cidade para nome de exibição.
    CORRIGIDO: CITY_DISPLAY usa chaves com espaco ('new york');
    a funcao recebia slug com hifen ('new-york') e nunca encontrava.
    Agora tenta slug direto e depois converte para espaco.
    """
    if not city_slug:
        return "Unknown"
    # Tenta lookup direto (caso alguma chave esteja em slug format)
    normalized = CITY_DISPLAY.get(city_slug)
    if normalized:
        return normalized
    # Converte slug para formato com espaco (ex.: 'new-york' -> 'new york')
    space_key = city_slug.replace("-", " ").replace("_", " ").lower()
    normalized = CITY_DISPLAY.get(space_key)
    if normalized:
        return normalized
    # Fallback: capitaliza
    return space_key.title()


def check_balance_invariant(data: Dict[str, Any], tolerance: float = 0.05) -> float:
    """
    Divergencia = balance_real - (start - stakes_abertos + pnl_fechados).
    0 (dentro da tolerancia) = consistente. Loga quando diverge.
    """
    history = data.get("history", [])
    start = float(data.get("start_balance", 0))
    balance = float(data.get("balance", 0))
    open_stakes = sum(
        float(t.get("stake", 0) or 0)
        for t in history if t.get("result") == "OPEN"
    )
    closed_pnl = sum(
        float(t.get("pnl", 0) or 0)
        for t in history if t.get("result") in ("WIN", "LOSS")
    )
    expected = start - open_stakes + closed_pnl
    diff = round(balance - expected, 4)
    if abs(diff) > tolerance:
        logger.warning(
            f"[invariante] DIVERGÊNCIA DE BANKROLL: saldo=${balance:.4f} "
            f"esperado=${expected:.4f} (diff {diff:+.4f})"
        )
    return diff


def force_close_open_trades(market_date_str):
    closed = {"n": 0}

    def _mutator(data):
        fechados = 0
        for trade in data.get("history", []):
            if trade.get("result") != "OPEN":
                continue
            mdate = trade.get("market_date", "")
            if mdate <= market_date_str:
                stake = float(trade.get("stake", 0))
                trade["result"] = "LOSS"
                trade["pnl"] = round(-stake, 2)
                trade["fee"] = 0.0
                trade["exit_time"] = datetime.now(timezone.utc).isoformat()
                logger.info(f"Fechando LOSS: {trade.get('city')} {mdate} ${stake:.2f}")
                fechados += 1
        closed["n"] = fechados
        if fechados == 0:
            logger.info("Nenhum trade encontrado para fechar.")
            return False
        return True

    data = atomic_update(_mutator)
    if closed["n"] > 0:
        logger.info(f"{closed['n']} trades fechados. Saldo: ${data['balance']:.2f}")
    return closed["n"]


def reset_bankroll(starting_balance=None):
    balance = starting_balance if starting_balance is not None else START_BALANCE

    def _mutator(data):
        data.clear()
        data.update({
            "balance": balance,
            "start_balance": balance,
            "history": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "seq": 0,
        })
        return True

    atomic_update(_mutator)
    logger.info(f"Bankroll resetado. Saldo inicial: ${balance:.2f}")
