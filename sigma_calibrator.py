"""
Calibrador de Sigma por Cidade baseado em erros de previsão observados.

CORRIGIDO:
- A versão anterior salvava em sigma_calibration.json no filesystem local.
  No Railway, o filesystem é efêmero — o arquivo é perdido a cada deploy,
  zerando o aprendizado. Agora tenta persistir no PostgreSQL (mesma tabela
  do bankroll) e usa o arquivo local apenas como cache de sessão.
- Fallback limpo se PostgreSQL não estiver configurado.
"""

import json
import os
import logging
from datetime import datetime, timezone
from typing import Dict

logger = logging.getLogger(__name__)

SIGMA_CALIBRATION_FILE = "sigma_calibration.json"
_DB_KEY = "sigma_calibration"


class SigmaCalibrator:
    def __init__(self):
        self.calibration_data: Dict = self._load()

    # ──────────────────────────────────────────────────────
    # PERSISTÊNCIA
    # ──────────────────────────────────────────────────────

    def _load(self) -> Dict:
        # 1. Tenta PostgreSQL
        data = self._load_from_db()
        if data:
            return data
        # 2. Fallback: arquivo local
        if os.path.exists(SIGMA_CALIBRATION_FILE):
            try:
                with open(SIGMA_CALIBRATION_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"sigma_calibration.json corrompido: {e}")
        return {}

    def _load_from_db(self) -> Dict:
        url = os.environ.get("DATABASE_URL", "")
        if not url:
            return {}
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
                cur.execute("SELECT value FROM kv_store WHERE key = %s", (_DB_KEY,))
                row = cur.fetchone()
            conn.close()
            return row[0] if row else {}
        except Exception as e:
            logger.debug(f"[sigma_calibrator] db load: {e}")
            return {}

    def _save(self):
        # Sempre salva local (rápido)
        try:
            with open(SIGMA_CALIBRATION_FILE, "w", encoding="utf-8") as f:
                json.dump(self.calibration_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"sigma_calibration.json: {e}")

        # Persiste no PostgreSQL quando disponível
        url = os.environ.get("DATABASE_URL", "")
        if not url:
            return
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
                cur.execute("""
                    INSERT INTO kv_store (key, value)
                    VALUES (%s, %s)
                    ON CONFLICT (key) DO UPDATE
                        SET value = EXCLUDED.value,
                            saved_at = NOW()
                """, (_DB_KEY, json.dumps(self.calibration_data)))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug(f"[sigma_calibrator] db save: {e}")

    # ──────────────────────────────────────────────────────
    # API PÚBLICA
    # ──────────────────────────────────────────────────────

    def record_trade_result(
        self,
        city: str,
        day_offset: int,
        predicted_temp: float,
        actual_temp: float,
    ):
        """
        Registra erro de previsão e recalcula ajuste de sigma para a cidade.
        """
        city_key = city.strip().lower()
        error    = abs(predicted_temp - actual_temp)

        if city_key not in self.calibration_data:
            self.calibration_data[city_key] = {
                "errors": [],
                "current_sigma_adjustment": 0.0,
            }

        self.calibration_data[city_key]["errors"].append({
            "day_offset": day_offset,
            "error":      round(error, 2),
            "timestamp":  datetime.now(timezone.utc).isoformat(),
        })

        # Mantém janela de 30 observações
        if len(self.calibration_data[city_key]["errors"]) > 30:
            self.calibration_data[city_key]["errors"] = (
                self.calibration_data[city_key]["errors"][-30:]
            )

        # Recalcula ajuste com os erros do mesmo day_offset
        recent = [
            e["error"]
            for e in self.calibration_data[city_key]["errors"]
            if e["day_offset"] == day_offset
        ]
        if recent:
            mean_error = sum(recent) / len(recent)
            # Aumenta sigma proporcionalmente se erro médio > 2°C
            adjustment = max(0.0, (mean_error - 2.0) * 0.5)
            self.calibration_data[city_key]["current_sigma_adjustment"] = round(adjustment, 2)

        self._save()
        logger.info(
            f"Sigma calibrado: {city_key} d{day_offset} "
            f"ajuste=+{self.calibration_data[city_key]['current_sigma_adjustment']}°C"
        )

    def get_adjusted_sigma(self, city: str, base_sigma: float) -> float:
        """Retorna sigma ajustado pela calibração histórica da cidade."""
        city_key   = city.strip().lower()
        adjustment = (
            self.calibration_data
            .get(city_key, {})
            .get("current_sigma_adjustment", 0.0)
        )
        return round(base_sigma + adjustment, 4)
