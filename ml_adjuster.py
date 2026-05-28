"""
Ajuste de probabilidade via Regressão Logística online.

CORRIGIDO:
- A versão anterior salvava o modelo em ml_adjuster.pkl no filesystem local.
  No Railway, o filesystem é efêmero — o modelo é perdido a cada deploy,
  zerando o aprendizado. Agora persiste o modelo serializado no PostgreSQL
  (tabela kv_store, mesma usada pelo SigmaCalibrator).
- Fallback limpo: se não houver DB, usa arquivo local como antes.
"""

import os
import io
import pickle
import logging
from typing import Optional

import numpy as np
from sklearn.linear_model import SGDClassifier

logger = logging.getLogger(__name__)

MODEL_FILE = "ml_adjuster.pkl"
_DB_KEY    = "ml_adjuster_pkl"


class MLProbabilityAdjuster:
    def __init__(self):
        self.model: Optional[SGDClassifier] = None
        self._init_model()

    # ──────────────────────────────────────────────────────
    # PERSISTÊNCIA
    # ──────────────────────────────────────────────────────

    def _load_pkl_bytes(self) -> Optional[bytes]:
        """Tenta carregar bytes do modelo do PostgreSQL, depois do arquivo local."""
        # 1. PostgreSQL
        url = os.environ.get("DATABASE_URL", "")
        if url:
            try:
                import psycopg2
                conn = psycopg2.connect(url, sslmode="require")
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS kv_store (
                            key      TEXT PRIMARY KEY,
                            value    JSONB NOT NULL,
                            saved_at TIMESTAMP DEFAULT NOW()
                        )
                    """)
                    conn.commit()
                    cur.execute(
                        "SELECT value FROM kv_store WHERE key = %s",
                        (_DB_KEY,)
                    )
                    row = cur.fetchone()
                conn.close()
                if row and row[0]:
                    import base64
                    return base64.b64decode(row[0].get("pkl_b64", ""))
            except Exception as e:
                logger.debug(f"[ml_adjuster] db load: {e}")

        # 2. Arquivo local
        if os.path.exists(MODEL_FILE):
            try:
                with open(MODEL_FILE, "rb") as f:
                    return f.read()
            except Exception:
                pass
        return None

    def _save_pkl_bytes(self, data: bytes):
        """Salva bytes do modelo no arquivo local e no PostgreSQL."""
        # Local (rápido)
        try:
            with open(MODEL_FILE, "wb") as f:
                f.write(data)
        except Exception as e:
            logger.warning(f"ml_adjuster.pkl: {e}")

        # PostgreSQL
        url = os.environ.get("DATABASE_URL", "")
        if not url:
            return
        try:
            import psycopg2
            import base64
            import json
            conn = psycopg2.connect(url, sslmode="require")
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO kv_store (key, value)
                    VALUES (%s, %s)
                    ON CONFLICT (key) DO UPDATE
                        SET value = EXCLUDED.value,
                            saved_at = NOW()
                """, (
                    _DB_KEY,
                    json.dumps({"pkl_b64": base64.b64encode(data).decode()}),
                ))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug(f"[ml_adjuster] db save: {e}")

    # ──────────────────────────────────────────────────────
    # INICIALIZAÇÃO
    # ──────────────────────────────────────────────────────

    def _init_model(self):
        pkl_bytes = self._load_pkl_bytes()
        if pkl_bytes:
            try:
                self.model = pickle.loads(pkl_bytes)
                logger.info("Modelo ML carregado.")
                return
            except Exception as e:
                logger.warning(f"Erro ao desserializar modelo ML: {e}. Criando novo.")

        # Modelo novo com treino inicial (precisa de ambas as classes)
        self.model = SGDClassifier(loss="log_loss", random_state=42)
        X_init = np.array([
            [0.7, 1, 2.0, 1.0,  0.0],
            [0.3, 3, 3.5, 1.5, -0.5],
        ])
        y_init = np.array([1, 0])
        self.model.partial_fit(X_init, y_init, classes=np.array([0, 1]))

    def _save_model(self):
        data = pickle.dumps(self.model)
        self._save_pkl_bytes(data)

    # ──────────────────────────────────────────────────────
    # API PÚBLICA
    # ──────────────────────────────────────────────────────

    def compute_features(
        self,
        model_prob: float,
        day_offset: int,
        city_errors: list,
    ) -> np.ndarray:
        if not city_errors:
            mean_err, std_err = 2.0, 1.0
        else:
            mean_err = np.mean(city_errors)
            std_err  = np.std(city_errors) if len(city_errors) > 1 else 1.0

        recent_trend = 0.0
        if len(city_errors) >= 2:
            recent_trend = city_errors[-1] - city_errors[-2]

        return np.array(
            [model_prob, day_offset, mean_err, std_err, recent_trend]
        ).reshape(1, -1)

    def adjust_probability(
        self,
        model_prob: float,
        day_offset: int,
        city: str,
        calibrator,
    ) -> float:
        city_key = city.strip().lower()
        errors   = [
            e["error"]
            for e in calibrator.calibration_data.get(city_key, {}).get("errors", [])
        ]
        X     = self.compute_features(model_prob, day_offset, errors)
        proba = self.model.predict_proba(X)[0]

        # Aplica ajuste ML somente com dados suficientes (≥5 observações)
        if len(errors) >= 5:
            adjusted = 0.7 * model_prob + 0.3 * proba[1]
        else:
            adjusted = model_prob

        return float(max(0.0, min(1.0, adjusted)))

    def update(
        self,
        model_prob: float,
        day_offset: int,
        city: str,
        calibrator,
        trade_success: bool,
    ):
        city_key = city.strip().lower()
        errors   = [
            e["error"]
            for e in calibrator.calibration_data.get(city_key, {}).get("errors", [])
        ]
        X = self.compute_features(model_prob, day_offset, errors)
        y = np.array([1 if trade_success else 0])
        self.model.partial_fit(X, y)
        self._save_model()
        logger.info("Modelo ML atualizado.")
