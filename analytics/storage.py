"""
analytics.storage

Persistência do Analytics Engine.

Características:

- Escrita atômica
- Versionamento
- Checksum
- Compatível com futuras migrações
- Não depende do bankroll.py
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any


ANALYTICS_FILE = "analytics/analytics.json"

TMP_SUFFIX = ".tmp"

SCHEMA_VERSION = 1


# --------------------------------------------------------
# Helpers
# --------------------------------------------------------

def _json_default(obj):

    if isinstance(obj, datetime):
        return obj.isoformat()

    if is_dataclass(obj):
        return asdict(obj)

    raise TypeError(f"Objeto não serializável: {type(obj)}")


def _checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _ensure_dir():

    directory = os.path.dirname(ANALYTICS_FILE)

    if directory:
        os.makedirs(directory, exist_ok=True)


# --------------------------------------------------------
# Save
# --------------------------------------------------------

def save_snapshot(snapshot):

    _ensure_dir()

    payload = {

        "schema": SCHEMA_VERSION,

        "generated_at": datetime.now(timezone.utc).isoformat(),

        "snapshot": snapshot

    }

    encoded = json.dumps(
        payload,
        default=_json_default,
        indent=4,
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")

    wrapper = {

        "checksum": _checksum(encoded),

        "payload": json.loads(encoded)

    }

    tmp = ANALYTICS_FILE + TMP_SUFFIX

    with open(tmp, "w", encoding="utf-8") as f:

        json.dump(
            wrapper,
            f,
            indent=4,
            ensure_ascii=False,
        )

        f.flush()

        os.fsync(f.fileno())

    os.replace(tmp, ANALYTICS_FILE)


# --------------------------------------------------------
# Load
# --------------------------------------------------------

def load_snapshot():

    if not os.path.exists(ANALYTICS_FILE):

        return None

    with open(ANALYTICS_FILE, "r", encoding="utf-8") as f:

        wrapper = json.load(f)

    checksum = wrapper["checksum"]

    payload = wrapper["payload"]

    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        indent=4,
        sort_keys=True,
    ).encode("utf-8")

    if checksum != _checksum(encoded):

        raise RuntimeError("analytics.json corrompido")

    return payload


# --------------------------------------------------------
# Exists
# --------------------------------------------------------

def exists():

    return os.path.exists(ANALYTICS_FILE)


# --------------------------------------------------------
# Delete
# --------------------------------------------------------

def delete():

    if exists():

        os.remove(ANALYTICS_FILE)
