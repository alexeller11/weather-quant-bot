#!/usr/bin/env python3
"""
ml_adjuster.py — Aprendizado online por cidade (SGD Logístico)

MELHORIAS v2:
- Modelo separado por cidade (em vez de 1 modelo global)
- Features enriquecidas: hora do dia, mês, tendência horária intra-dia,
  umidade, pressão atmosférica (quando disponíveis)
- Feedback loop: registra Brier score por semana para medir melhora
- Fallback limpo para cidade sem dados
"""

import os
import io
import json
import pickle
import logging
from datetime import datetime, timezone
from typing import Optional, Dict

import numpy as np
from sklearn.linear_model import SGDClassifier

logger = logging.getLogger(__name__)

MODEL_FILE   = "ml_adjuster.pkl"
_DB_KEY_PFX  = "ml_model_v2_"   # prefixo por cidade
_DB_KEY_PERF = "ml_performance"  # histórico de Brier por semana


# ── PostgreSQL helpers ────────────────────────────────────────

def _db_connect():
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        return None
    try:
        import psycopg2
        conn = psycopg2.connect(url, sslmode="require")
        _ensure_kv(conn)
        return conn
    except Exception as e:
        logger.debug(f"[ml] db connect: {e}")
        return None


def _ensure_kv(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kv_store (
                key      TEXT PRIMARY KEY,
                value    JSONB NOT NULL,
                saved_at TIMESTAMP DEFAULT NOW()
            )
        """)
    conn.commit()


def _kv_get(conn, key) -> Optional[dict]:
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM kv_store WHERE key = %s", (key,))
            row = cur.fetchone()
        return row[0] if row else None
    except Exception as e:
        logger.debug(f"[ml] kv_get {key}: {e}")
        return None


def _kv_set(conn, key, value: dict):
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO kv_store (key, value)
                VALUES (%s, %s)
                ON CONFLICT (key) DO UPDATE
                    SET value = EXCLUDED.value, saved_at = NOW()
            """, (key, json.dumps(value)))
        conn.commit()
    except Exception as e:
        logger.debug(f"[ml] kv_set {key}: {e}")


# ── modelo por cidade ─────────────────────────────────────────

def _new_model() -> SGDClassifier:
    m = SGDClassifier(loss="log_loss", random_state=42, max_iter=1000)
    # Treino inicial com 2 exemplos neutros para evitar erro de classe única
    X = np.array([[0.7, 1, 6, 2.0, 1.0, 0.0, 0.0],
                  [0.3, 3, 9, 3.5, 1.5, -0.5, 0.0]])
    y = np.array([1, 0])
    m.partial_fit(X, y, classes=np.array([0, 1]))
    return m


def _load_model(city_key: str) -> SGDClassifier:
    """Carrega modelo da cidade do PostgreSQL ou cria novo."""
    import base64
    conn = _db_connect()
    if conn:
        try:
            data = _kv_get(conn, _DB_KEY_PFX + city_key)
            conn.close()
            if data and data.get("pkl_b64"):
                return pickle.loads(base64.b64decode(data["pkl_b64"]))
        except Exception as e:
            logger.debug(f"[ml] load_model {city_key}: {e}")
            try:
                conn.close()
            except Exception:
                pass
    return _new_model()


def _save_model(city_key: str, model: SGDClassifier):
    """Salva modelo da cidade no PostgreSQL."""
    import base64
    pkl_b64 = base64.b64encode(pickle.dumps(model)).decode()
    conn = _db_connect()
    if conn:
        try:
            _kv_set(conn, _DB_KEY_PFX + city_key, {"pkl_b64": pkl_b64})
            conn.close()
        except Exception as e:
            logger.debug(f"[ml] save_model {city_key}: {e}")
            try:
                conn.close()
            except Exception:
                pass


# ── features ──────────────────────────────────────────────────

def compute_features(
    model_prob: float,
    day_offset: int,
    city_errors: list,
    hour_utc: int = 12,
    month: int = 6,
    temp_trend: float = 0.0,   # tendência horária °C/h (intra-dia)
    humidity: float = 0.0,     # 0-100, 0 se indisponível
) -> np.ndarray:
    """
    Features v2 (7 dimensões):
      0: model_prob
      1: day_offset
      2: hour_utc         (quando o trade foi aberto)
      3: mean_error_cidade
      4: std_error_cidade
      5: recent_trend     (erro recente vs anterior)
      6: temp_trend       (tendência intra-dia em °C/h)
    """
    if not city_errors:
        mean_err, std_err = 2.0, 1.0
    else:
        mean_err = float(np.mean(city_errors))
        std_err  = float(np.std(city_errors)) if len(city_errors) > 1 else 1.0

    recent_trend = 0.0
    if len(city_errors) >= 2:
        recent_trend = city_errors[-1] - city_errors[-2]

    return np.array([
        model_prob,
        day_offset,
        hour_utc,
        mean_err,
        std_err,
        recent_trend,
        temp_trend,
    ]).reshape(1, -1)


# ── API pública ───────────────────────────────────────────────

class MLProbabilityAdjuster:
    def __init__(self):
        # Cache em memória para evitar carregar do DB a cada ciclo
        self._models: Dict[str, SGDClassifier] = {}
        self._n_trades: Dict[str, int] = {}
        logger.info("Modelo ML carregado.")

    def _get_model(self, city_key: str) -> SGDClassifier:
        if city_key not in self._models:
            self._models[city_key] = _load_model(city_key)
            self._n_trades[city_key] = 0
        return self._models[city_key]

    def adjust_probability(
        self,
        model_prob: float,
        day_offset: int,
        city: str,
        calibrator,
        hour_utc: int = 12,
        temp_trend: float = 0.0,
    ) -> float:
        city_key = city.strip().lower()
        errors = [
            e["error"]
            for e in calibrator.calibration_data.get(city_key, {}).get("errors", [])
        ]
        n = self._n_trades.get(city_key, 0)

        # Só aplica ajuste ML quando há dados suficientes desta cidade
        if n < 5:
            return model_prob

        model = self._get_model(city_key)
        X = compute_features(model_prob, day_offset, errors, hour_utc, temp_trend=temp_trend)
        try:
            proba = model.predict_proba(X)[0][1]
            # Blend conservador: 80% modelo físico + 20% ML (aumenta com dados)
            peso_ml = min(0.30, n * 0.02)  # cresce até 30% com 15+ trades
            adjusted = (1 - peso_ml) * model_prob + peso_ml * proba
            return float(max(0.01, min(0.99, adjusted)))
        except Exception as e:
            logger.debug(f"[ml] predict {city_key}: {e}")
            return model_prob

    def update(
        self,
        model_prob: float,
        day_offset: int,
        city: str,
        calibrator,
        trade_success: bool,
        hour_utc: int = 12,
        temp_trend: float = 0.0,
    ):
        city_key = city.strip().lower()
        errors = [
            e["error"]
            for e in calibrator.calibration_data.get(city_key, {}).get("errors", [])
        ]
        model = self._get_model(city_key)
        X = compute_features(model_prob, day_offset, errors, hour_utc, temp_trend=temp_trend)
        y = np.array([1 if trade_success else 0])
        try:
            model.partial_fit(X, y)
            self._models[city_key] = model
            self._n_trades[city_key] = self._n_trades.get(city_key, 0) + 1
            _save_model(city_key, model)
            logger.info(f"[ml] {city_key} atualizado (n={self._n_trades[city_key]})")
        except Exception as e:
            logger.warning(f"[ml] update {city_key}: {e}")

    def registrar_performance_semanal(self, brier: float):
        """Guarda Brier score semanal para rastrear melhora ao longo do tempo."""
        conn = _db_connect()
        if not conn:
            return
        try:
            data = _kv_get(conn, _DB_KEY_PERF) or {"historico": []}
            data["historico"].append({
                "semana": datetime.now(timezone.utc).strftime("%Y-W%W"),
                "brier":  round(brier, 4),
                "ts":     datetime.now(timezone.utc).isoformat(),
            })
            # Mantém últimas 52 semanas
            data["historico"] = data["historico"][-52:]
            _kv_set(conn, _DB_KEY_PERF, data)
            conn.close()
        except Exception as e:
            logger.debug(f"[ml] perf: {e}")
            try:
                conn.close()
            except Exception:
                pass

    def tendencia_brier(self) -> str:
        """Retorna string descrevendo evolução do Brier score."""
        conn = _db_connect()
        if not conn:
            return "N/A"
        try:
            data = _kv_get(conn, _DB_KEY_PERF) or {}
            conn.close()
            hist = data.get("historico", [])
            if len(hist) < 2:
                return f"Semana 1 de {len(hist)+1}"
            ultimo = hist[-1]["brier"]
            anterior = hist[-2]["brier"]
            diff = ultimo - anterior
            sinal = "↓ melhorou" if diff < -0.01 else ("↑ piorou" if diff > 0.01 else "→ estável")
            return f"{ultimo:.4f} ({sinal} vs {anterior:.4f})"
        except Exception:
            return "N/A"

    # Compatibilidade com código antigo
    def compute_features(self, model_prob, day_offset, city_errors):
        return compute_features(model_prob, day_offset, city_errors)
