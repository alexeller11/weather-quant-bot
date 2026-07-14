"""
analytics.registry

Registry do Quant Intelligence Engine.

Responsável por registrar e executar métricas.

Exemplo:

registry.register(
    "roi",
    finance.roi
)

registry.register(
    "brier",
    statistics.brier_score
)

result = registry.execute(dataset)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Any


# ============================================================
# Modelo
# ============================================================

@dataclass
class Metric:

    name: str

    func: Callable

    category: str = "general"

    enabled: bool = True


# ============================================================
# Registry
# ============================================================

class MetricsRegistry:

    def __init__(self):

        self._metrics: Dict[str, Metric] = {}

    # --------------------------------------------------------

    def register(
        self,
        name: str,
        func: Callable,
        category: str = "general",
    ):

        if name in self._metrics:

            raise ValueError(
                f"Métrica '{name}' já registrada."
            )

        self._metrics[name] = Metric(

            name=name,

            func=func,

            category=category,

        )

    # --------------------------------------------------------

    def unregister(self, name: str):

        self._metrics.pop(name, None)

    # --------------------------------------------------------

    def exists(self, name: str):

        return name in self._metrics

    # --------------------------------------------------------

    def enable(self, name: str):

        if name in self._metrics:

            self._metrics[name].enabled = True

    # --------------------------------------------------------

    def disable(self, name: str):

        if name in self._metrics:

            self._metrics[name].enabled = False

    # --------------------------------------------------------

    def clear(self):

        self._metrics.clear()

    # --------------------------------------------------------

    def metrics(self):

        return list(self._metrics.values())

    # --------------------------------------------------------

    def names(self):

        return sorted(self._metrics.keys())

    # --------------------------------------------------------

    def execute(self, dataset):

        result = {}

        for metric in self._metrics.values():

            if not metric.enabled:

                continue

            try:

                result[metric.name] = metric.func(dataset)

            except Exception as exc:

                result[metric.name] = {

                    "error": str(exc)

                }

        return result

    # --------------------------------------------------------

    def execute_category(
        self,
        category,
        dataset,
    ):

        result = {}

        for metric in self._metrics.values():

            if not metric.enabled:

                continue

            if metric.category != category:

                continue

            try:

                result[metric.name] = metric.func(dataset)

            except Exception as exc:

                result[metric.name] = {

                    "error": str(exc)

                }

        return result


# ============================================================
# Singleton
# ============================================================

registry = MetricsRegistry()
