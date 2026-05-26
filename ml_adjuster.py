"""
Ajuste de probabilidade via Regressão Logística online.
Utiliza features derivadas do erro histórico para refinar a estimativa do modelo base.
"""

import os
import logging
import pickle
from typing import Optional
import numpy as np
from sklearn.linear_model import SGDClassifier  # permite aprendizado incremental

logger = logging.getLogger(__name__)

MODEL_FILE = "ml_adjuster.pkl"


class MLProbabilityAdjuster:
    def __init__(self):
        self.model: Optional[SGDClassifier] = None
        self.feature_names = [
            "model_prob",
            "day_offset",
            "city_error_mean",
            "city_error_std",
            "recent_trend"
        ]
        self._init_model()

    def _init_model(self):
        if os.path.exists(MODEL_FILE):
            try:
                with open(MODEL_FILE, "rb") as f:
                    self.model = pickle.load(f)
                logger.info("Modelo ML carregado do disco.")
            except Exception as e:
                logger.warning(f"Erro ao carregar modelo ML: {e}. Criando novo.")
                self.model = SGDClassifier(loss="log_loss", random_state=42)
        else:
            self.model = SGDClassifier(loss="log_loss", random_state=42)
            # Treino inicial com dados dummy para ter ambas as classes
            X_init = np.array([
                [0.7, 1, 2.0, 1.0, 0.0],
                [0.3, 3, 3.5, 1.5, -0.5]
            ])
            y_init = np.array([1, 0])
            self.model.partial_fit(X_init, y_init, classes=np.array([0, 1]))

    def _save_model(self):
        with open(MODEL_FILE, "wb") as f:
            pickle.dump(self.model, f)

    def compute_features(self, model_prob: float, day_offset: int,
                         city_errors: list) -> np.ndarray:
        """
        Calcula o vetor de features a partir dos dados disponíveis.
        city_errors: lista de erros absolutos dos últimos trades na cidade (float).
        """
        if not city_errors:
            mean_err, std_err = 2.0, 1.0  # defaults conservadores
        else:
            mean_err = np.mean(city_errors)
            std_err = np.std(city_errors) if len(city_errors) > 1 else 1.0

        # Tendência recente: diferença entre os dois últimos erros (se houver)
        recent_trend = 0.0
        if len(city_errors) >= 2:
            recent_trend = city_errors[-1] - city_errors[-2]

        return np.array([model_prob, day_offset, mean_err, std_err, recent_trend]).reshape(1, -1)

    def adjust_probability(
        self,
        model_prob: float,
        day_offset: int,
        city: str,
        calibrator
    ) -> float:
        """
        Retorna probabilidade ajustada.
        Usa o histórico de erros do SigmaCalibrator (calibrator) para extrair features.
        """
        city_key = city.strip().lower()
        errors = [
            e["error"]
            for e in calibrator.calibration_data.get(city_key, {}).get("errors", [])
        ]
        X = self.compute_features(model_prob, day_offset, errors)
        # predict_proba retorna [prob_classe_0, prob_classe_1]
        proba = self.model.predict_proba(X)[0]
        # A probabilidade ajustada é uma combinação da original com a saída do modelo
        # (apenas se houver dados suficientes)
        if len(errors) >= 5:
            adjusted = 0.7 * model_prob + 0.3 * proba[1]  # peso para o modelo
        else:
            adjusted = model_prob
        return max(0.0, min(1.0, adjusted))

    def update(
        self,
        model_prob: float,
        day_offset: int,
        city: str,
        calibrator,
        trade_success: bool
    ):
        """
        Atualiza o modelo online com o resultado do trade.
        trade_success: True se o trade foi lucrativo (acertou a direção), False caso contrário.
        """
        city_key = city.strip().lower()
        errors = [
            e["error"]
            for e in calibrator.calibration_data.get(city_key, {}).get("errors", [])
        ]
        X = self.compute_features(model_prob, day_offset, errors)
        y = np.array([1 if trade_success else 0])
        self.model.partial_fit(X, y)
        self._save_model()
        logger.info("Modelo ML atualizado com novo trade.")