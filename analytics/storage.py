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
import os
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path

# ============================================================
# Config
# ============================================================

BASE = Path("analytics")

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


def atomic_read(path: Path):

    if not path.exists():

        return None

    with open(

        path,

        encoding="utf8"

    ) as f:

        wrapper = json.load(f)

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


def load_health():

    return atomic_read(

        HEALTH_FILE

    )


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
