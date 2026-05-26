"""
Calibrador de Sigma por Cidade baseado em erros de previsão observados.
Aprende com trades liquidados para ajustar a incerteza do modelo.
"""

import json
import os
import logging
from datetime import datetime
from typing import Dict, Optional

logger = logging.getLogger(__name__)

SIGMA_CALIBRATION_FILE = "sigma_calibration.json"
DEFAULT_SIGMA_BASE = 2.8  # valor base inicial


class SigmaCalibrator:
    def __init__(self):
        self.calibration_data = self._load()

    def _load(self) -> Dict:
        if os.path.exists(SIGMA_CALIBRATION_FILE):
            with open(SIGMA_CALIBRATION_FILE, "r") as f:
                return json.load(f)
        return {}

    def _save(self):
        with open(SIGMA_CALIBRATION_FILE, "w") as f:
            json.dump(self.calibration_data, f, indent=2)

    def record_trade_result(
        self,
        city: str,
        day_offset: int,
        predicted_temp: float,
        actual_temp: float
    ):
        """
        Registra o erro de previsão após a liquidação de um trade.
        city: nome padronizado da cidade (ex: "New York")
        day_offset: dias de antecedência da previsão (1, 2, 3...)
        """
        city_key = city.strip().lower()
        error = abs(predicted_temp - actual_temp)

        if city_key not in self.calibration_data:
            self.calibration_data[city_key] = {
                "errors": [],
                "current_sigma_adjustment": 0.0
            }

        # Adiciona erro e mantém apenas os últimos 30
        self.calibration_data[city_key]["errors"].append({
            "day_offset": day_offset,
            "error": round(error, 2),
            "timestamp": datetime.now().isoformat()
        })
        if len(self.calibration_data[city_key]["errors"]) > 30:
            self.calibration_data[city_key]["errors"] = \
                self.calibration_data[city_key]["errors"][-30:]

        # Recalcula ajuste: média dos erros recentes para aquele day_offset
        recent_errors = [
            e["error"]
            for e in self.calibration_data[city_key]["errors"]
            if e["day_offset"] == day_offset
        ]
        if recent_errors:
            mean_error = sum(recent_errors) / len(recent_errors)
            # Se o erro médio exceder 2°C, aumentamos o sigma proporcionalmente
            adjustment = max(0, (mean_error - 2.0) * 0.5)  # fator 0.5 conservador
            self.calibration_data[city_key]["current_sigma_adjustment"] = round(adjustment, 2)

        self._save()
        logger.info(
            f"Sigma calibrado para {city_key} (day_offset={day_offset}): "
            f"ajuste=+{self.calibration_data[city_key]['current_sigma_adjustment']}°C"
        )

    def get_adjusted_sigma(self, city: str, base_sigma: float) -> float:
        """
        Retorna o sigma ajustado para a cidade.
        base_sigma: sigma base do modelo (dependendo do day_offset).
        """
        city_key = city.strip().lower()
        adjustment = self.calibration_data.get(city_key, {}).get(
            "current_sigma_adjustment", 0.0
        )
        return base_sigma + adjustment