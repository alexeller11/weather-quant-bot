#!/usr/bin/env python3
"""
ml_adjuster.py — Aprendizado online por cidade (SGD Logístico)

MELHORIAS v2:
- Modelo separado por cidade (em vez de 1 modelo global)
- Features enriquecidas: hora do dia, mês, tendência horária intra-dia,
  umidade, pressão atmosférica (quando disponíveis)
- Feedback loop: registra Brier score por semana para medir melhora
- Fallback limpo para cidade sem dados

CORREÇÕES v3 (auditoria):
1. Os erros da cidade agora vêm de calibrator.get_recent_errors(city).
   A leitura antiga (calibration_data[city]["errors"]) apontava para um
   nível inexistente da estrutura (que é [city][COND]["errors"]) e
   retornava SEMPRE lista vazia — as features 3, 4 e 5 estavam mortas
   silenciosamente.
2. n_trades agora é persistido junto com o modelo no kv_store
   ({"pkl_b64", "n_trades"}). Antes ficava só em memória e zerava a cada
   deploy/restart, fazendo o gate `n >= 5` quase nunca passar: o ML era
   treinado mas praticamente nunca aplicado.
3. Features normalizadas para escalas comparáveis (~[0,1]) antes do SGD.
   O SGD sem normalização era dominado por hour_utc (0–23) e day_offset.
   O prefixo de chave do modelo subiu para "ml_model_v3_" para NÃO
   misturar pickles treinados na escala antiga com a nova.
4. update() recebe hour_utc real do trade (passado pelo settlement a
   partir do entry_time) — antes treinava com a hora da liquidação e
   servia com hour=12 fixo (train/serve skew).
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
_DB_KEY_PFX  = "ml_model_v3_"    # prefixo por cidade (v3: features normalizadas)
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
    # Treino inicial com 2 exemplos neutros (já na escala NORMALIZADA)
    # para evitar erro de classe única no primeiro partial_fit real.
    X = np.array([
        # prob, day/3, hour/24, mean/5, std/5, trend/5, temp_trend/5
        [0.7, 1 / 3.0,  6 / 24.0, 2.0 / 5.0, 1.0 / 5.0,  0.0,        0.0],
        [0.3, 3 / 3.0,  9 / 24.0, 3.5 / 5.0, 1.5 / 5.0, -0.5 / 5.0,  0.0],
    ])
    y = np.array([1, 0])
    m.partial_fit(X, y, classes=np.array([0, 1]))
    return m


def _load_model(city_key: str):
    """
    Carrega (modelo, n_trades) da cidade do PostgreSQL ou cria novo.
    Retorna tupla (SGDClassifier, int).
    """
    import base64
    conn = _db_connect()
    if conn:
        try:
            data = _kv_get(conn, _DB_KEY_PFX + city_key)
            conn.close()
            if data and data.get("pkl_b64"):
                model = pickle.loads(base64.b64decode(data["pkl_b64"]))
                n_trades = int(data.get("n_trades", 0))
                return model, n_trades
        except Exception as e:
            logger.debug(f"[ml] load_model {city_key}: {e}")
            try:
                conn.close()
            except Exception:
                pass
    return _new_model(), 0


def _save_model(city_key: str, model: SGDClassifier, n_trades: int):
    """Salva (modelo, n_trades) da cidade no PostgreSQL."""
    import base64
    pkl_b64 = base64.b64encode(pickle.dumps(model)).decode()
    conn = _db_connect()
    if conn:
        try:
            _kv_set(conn, _DB_KEY_PFX + city_key, {
                "pkl_b64":  pkl_b64,
                "n_trades": int(n_trades),
            })
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
    humidity: float = 0.0,     # 0-100, 0 se indisponível (reservado)
) -> np.ndarray:
    """
    Features v3 (7 dimensões, NORMALIZADAS para ~[0,1] / [-1,1]):
      0: model_prob          (já em [0,1])
      1: day_offset / 3
      2: hour_utc / 24       (quando o trade foi aberto)
      3: mean_error / 5      (erro médio da cidade, °C)
      4: std_error / 5
      5: recent_trend / 5    (erro recente vs anterior)
      6: temp_trend / 5      (tendência intra-dia °C/h)
    """
    if not city_errors:
        mean_err, std_err = 2.0, 1.0
    else:
        mean_err = float(np.mean(city_errors))
        std_err  = float(np.std(city_errors)) if len(city_errors) > 1 else 1.0

    recent_trend = 0.0
    if len(city_errors) >= 2:
        recent_trend = float(city_errors[-1]) - float(city_errors[-2])

    return np.array([
        float(model_prob),
        float(day_offset) / 3.0,
        float(hour_utc) / 24.0,
        mean_err / 5.0,
        std_err / 5.0,
        recent_trend / 5.0,
        float(temp_trend) / 5.0,
    ]).reshape(1, -1)


def _errors_for_city(calibrator, city_key: str) -> list:
    """
    Obtém a série de erros recentes da cidade de forma tolerante:
    usa o helper oficial do calibrador quando existir; caso contrário,
    percorre a estrutura aninhada [city][COND]["errors"] corretamente.
    """
    try:
        if hasattr(calibrator, "get_recent_errors"):
            return list(calibrator.get_recent_errors(city_key))
    except Exception as e:
        logger.debug(f"[ml] get_recent_errors {city_key}: {e}")

    # Fallback defensivo (estrutura aninhada por condição)
    out = []
    try:
        conds = calibrator.calibration_data.get(city_key, {})
        if isinstance(conds, dict):
            merged = []
            for data in conds.values():
                if isinstance(data, dict):
                    for e in data.get("errors", []):
                        if isinstance(e, dict) and "error" in e:
                            merged.append((e.get("timestamp", ""), float(e["error"])))
            merged.sort(key=lambda t: t[0])
            out = [v for _, v in merged]
    except Exception as e:
        logger.debug(f"[ml] errors fallback {city_key}: {e}")
    return out


# ── API pública ───────────────────────────────────────────────

class MLProbabilityAdjuster:
    def __init__(self):
        # Cache em memória para evitar carregar do DB a cada ciclo
        self._models: Dict[str, SGDClassifier] = {}
        self._n_trades: Dict[str, int] = {}
        logger.info("Modelo ML carregado.")

    def _get_model(self, city_key: str) -> SGDClassifier:
        if city_key not in self._models:
            model, n_trades = _load_model(city_key)
            self._models[city_key] = model
            self._n_trades[city_key] = n_trades
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

        # Garante que modelo + contador persistido estejam carregados
        # ANTES de checar o gate (o contador agora sobrevive a restarts).
        model = self._get_model(city_key)
        errors = _errors_for_city(calibrator, city_key)
        n = self._n_trades.get(city_key, 0)

        # Só aplica ajuste ML quando há dados suficientes desta cidade
        if n < 5:
            return model_prob

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
        errors = _errors_for_city(calibrator, city_key)
        model = self._get_model(city_key)
        X = compute_features(model_prob, day_offset, errors, hour_utc, temp_trend=temp_trend)
        y = np.array([1 if trade_success else 0])
        try:
            model.partial_fit(X, y)
            self._models[city_key] = model
            self._n_trades[city_key] = self._n_trades.get(city_key, 0) + 1
            _save_model(city_key, model, self._n_trades[city_key])
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
