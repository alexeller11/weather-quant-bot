"""
analytics.storage

Persistência do Analytics Engine.

Responsabilidades:

- salvar analytics.json
- carregar analytics.json
- salvar health.json
- carregar health.json
- salvar history_metrics.json

Escrita atômica
Checksum
Versionamento
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# ============================================================
# Config
# ============================================================

# Ancorado no próprio pacote, não no cwd: rodar `python settlement.py`
# de outra pasta escrevia analytics/ num lugar diferente do que bot.py lê.
BASE = Path(__file__).resolve().parent

ANALYTICS_FILE = BASE / "analytics.json"

HEALTH_FILE = BASE / "health.json"

HISTORY_FILE = BASE / "history_metrics.json"

SCHEMA_VERSION = 1


# ============================================================
# Helpers
# ============================================================

def ensure_directory():

    BASE.mkdir(
        parents=True,
        exist_ok=True
    )


def json_default(obj):

    if isinstance(obj, datetime):

        return obj.isoformat()

    if is_dataclass(obj):

        return asdict(obj)

    raise TypeError(type(obj))


def checksum(data: bytes):

    return hashlib.sha256(data).hexdigest()


def atomic_write(path: Path, payload):

    ensure_directory()

    encoded = json.dumps(

        payload,

        default=json_default,

        ensure_ascii=False,

        indent=4,

        sort_keys=True,

    ).encode()

    wrapper = {

        "schema": SCHEMA_VERSION,

        "generated_at": datetime.now(timezone.utc).isoformat(),

        "checksum": checksum(encoded),

        "payload": json.loads(encoded)

    }

    tmp = path.with_suffix(".tmp")

    with open(

        tmp,

        "w",

        encoding="utf8"

    ) as f:

        json.dump(

            wrapper,

            f,

            indent=4,

            ensure_ascii=False,

        )

        f.flush()

        os.fsync(f.fileno())

    os.replace(

        tmp,

        path

    )


def read_wrapper(path: Path):
    """Retorna o envelope completo (com generated_at), não só o payload."""

    if not path.exists():

        return None

    with open(path, encoding="utf8") as f:

        return json.load(f)


def atomic_read(path: Path):

    wrapper = read_wrapper(path)

    if wrapper is None:

        return None

    encoded = json.dumps(

        wrapper["payload"],

        ensure_ascii=False,

        indent=4,

        sort_keys=True,

    ).encode()

    if checksum(encoded) != wrapper["checksum"]:

        raise RuntimeError(

            f"{path.name} corrompido."

        )

    return wrapper["payload"]


# ============================================================
# Analytics
# ============================================================

def save_analytics(snapshot):

    atomic_write(

        ANALYTICS_FILE,

        snapshot

    )


def load_analytics():

    return atomic_read(

        ANALYTICS_FILE

    )


# ============================================================
# Health
# ============================================================

def save_health(health):

    atomic_write(

        HEALTH_FILE,

        health

    )


def load_health(max_age_hours: float = None):
    """
    Carrega health.json, ignorando snapshots velhos.

    O health vive no filesystem efêmero do Render. Um snapshot antigo
    (o versionado no repositório estava congelado há 15 dias) continuava a
    governar o kelly_factor a cada restart do processo. Acima de
    HEALTH_MAX_AGE_HOURS o health é descartado e o caller cai no
    comportamento neutro (factor 1.0), em vez de operar com um veredito
    de saúde obsoleto.
    """
    if max_age_hours is None:
        try:
            from config import HEALTH_MAX_AGE_HOURS
            max_age_hours = HEALTH_MAX_AGE_HOURS
        except Exception:
            max_age_hours = 48.0

    wrapper = read_wrapper(HEALTH_FILE)
    if wrapper is None:
        return None

    if max_age_hours and max_age_hours > 0:
        raw_ts = wrapper.get("generated_at")
        if raw_ts:
            try:
                generated = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
                if generated.tzinfo is None:
                    generated = generated.replace(tzinfo=timezone.utc)
                age_h = (datetime.now(timezone.utc) - generated).total_seconds() / 3600.0
                if age_h > max_age_hours:
                    logger.warning(
                        "health.json com %.1fh (> %.1fh) — ignorado, usando fator neutro",
                        age_h, max_age_hours,
                    )
                    return None
            except Exception as exc:
                logger.debug("health.json generated_at ilegivel: %s", exc)

    return atomic_read(HEALTH_FILE)


# ============================================================
# History
# ============================================================

def save_history(history):

    atomic_write(

        HISTORY_FILE,

        history

    )


def load_history():

    return atomic_read(

        HISTORY_FILE

    )


# ============================================================
# Exists
# ============================================================

def analytics_exists():

    return ANALYTICS_FILE.exists()


def health_exists():

    return HEALTH_FILE.exists()


def history_exists():

    return HISTORY_FILE.exists()


# ============================================================
# Delete
# ============================================================

def clear():

    for file in (

        ANALYTICS_FILE,

        HEALTH_FILE,

        HISTORY_FILE,

    ):

        if file.exists():

            file.unlink()
