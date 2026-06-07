#!/usr/bin/env python3
"""
sigma_calibrator.py — Calibração de Sigma por Cidade

MELHORIAS v2:
- Sigma separado por tipo (ABOVE/BELOW vs EXACT vs RANGE2)
- Decaimento temporal: erros recentes pesam mais que antigos
- Limite de ajuste: sigma não pode ficar abaixo de 2.0 nem acima de 8.0
- Log de evolução para diagnóstico
"""

import json
import os
import logging
from datetime import datetime, timezone
from typing import Dict

logger = logging.getLogger(__name__)

SIGMA_CALIBRATION_FILE = "sigma_calibration.json"
_DB_KEY = "sigma_calibration_v2"

SIGMA_MIN = 2.0
SIGMA_MAX = 8.0


class SigmaCalibrator:
    def __init__(self):
        self.calibration_data: Dict = self._load()

    # ── persistência ─────────────────────────────────────────

    def _load(self) -> Dict:
        data = self._load_from_db()
        if data:
            return data
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
                        key TEXT PRIMARY KEY,
                        value JSONB NOT NULL,
                        saved_at TIMESTAMP DEFAULT NOW()
                    )
                """)
                conn.commit()
                cur.execute("SELECT value FROM kv_store WHERE key = %s", (_DB_KEY,))
                row = cur.fetchone()
            conn.close()
            return row[0] if row else {}
        except Exception as e:
            logger.debug(f"[sigma] db load: {e}")
            return {}

    def _save(self):
        try:
            with open(SIGMA_CALIBRATION_FILE, "w", encoding="utf-8") as f:
                json.dump(self.calibration_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"sigma_calibration.json save: {e}")

        url = os.environ.get("DATABASE_URL", "")
        if not url:
            return
        try:
            import psycopg2
            conn = psycopg2.connect(url, sslmode="require")
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS kv_store (
                        key TEXT PRIMARY KEY,
                        value JSONB NOT NULL,
                        saved_at TIMESTAMP DEFAULT NOW()
                    )
                """)
                cur.execute("""
                    INSERT INTO kv_store (key, value)
                    VALUES (%s, %s)
                    ON CONFLICT (key) DO UPDATE
                        SET value = EXCLUDED.value, saved_at = NOW()
                """, (_DB_KEY, json.dumps(self.calibration_data)))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug(f"[sigma] db save: {e}")

    # ── API pública ───────────────────────────────────────────

    def record_trade_result(
        self,
        city: str,
        day_offset: int,
        predicted_temp: float,
        actual_temp: float,
        condition: str = "ABOVE",
    ):
        city_key = city.strip().lower()
        error    = abs(predicted_temp - actual_temp)
        cond_key = condition.upper()

        if city_key not in self.calibration_data:
            self.calibration_data[city_key] = {}

        if cond_key not in self.calibration_data[city_key]:
            self.calibration_data[city_key][cond_key] = {
                "errors": [],
                "sigma_adjustment": 0.0,
            }

        entry = {
            "day_offset": day_offset,
            "error":      round(error, 2),
            "timestamp":  datetime.now(timezone.utc).isoformat(),
        }
        self.calibration_data[city_key][cond_key]["errors"].append(entry)

        # Janela máxima de 40 observações
        self.calibration_data[city_key][cond_key]["errors"] = \
            self.calibration_data[city_key][cond_key]["errors"][-40:]

        # Recalcula ajuste com decaimento temporal
        errors_list = self.calibration_data[city_key][cond_key]["errors"]
        n = len(errors_list)
        if n >= 3:
            # Peso exponencial: erros mais recentes têm mais peso
            weights = [0.9 ** (n - 1 - i) for i in range(n)]
            w_sum   = sum(weights)
            w_mean  = sum(w * e["error"] for w, e in zip(weights, errors_list)) / w_sum

            # Ajuste: se erro médio ponderado > 2°C, aumenta sigma
            # EXACT usa base de 1.5°C (mais sensível)
            base_erro = 1.5 if cond_key == "EXACT" else 2.0
            adjustment = max(0.0, (w_mean - base_erro) * 0.6)
            self.calibration_data[city_key][cond_key]["sigma_adjustment"] = round(adjustment, 3)

            logger.info(
                f"[sigma] {city_key}/{cond_key} d{day_offset}: "
                f"err={error:.1f}°C w_mean={w_mean:.2f}°C adj=+{adjustment:.2f}°C (n={n})"
            )

        self._save()

    def get_adjusted_sigma(
        self,
        city: str,
        base_sigma: float,
        condition: str = "ABOVE",
    ) -> float:
        city_key = city.strip().lower()
        cond_key = condition.upper()

        adjustment = (
            self.calibration_data
            .get(city_key, {})
            .get(cond_key, {})
            .get("sigma_adjustment", 0.0)
        )

        sigma = base_sigma + adjustment
        sigma = max(SIGMA_MIN, min(SIGMA_MAX, sigma))
        return round(sigma, 4)

    def resumo_calibracao(self) -> str:
        """Retorna resumo legível da calibração atual por cidade."""
        linhas = []
        for city, conds in sorted(self.calibration_data.items()):
            for cond, data in conds.items():
                n   = len(data.get("errors", []))
                adj = data.get("sigma_adjustment", 0.0)
                if n > 0:
                    erros = [e["error"] for e in data["errors"]]
                    media = sum(erros) / len(erros)
                    linhas.append(
                        f"  {city}/{cond}: n={n} err_med={media:.1f}°C adj=+{adj:.2f}°C"
                    )
        return "\n".join(linhas) if linhas else "  sem dados ainda"
