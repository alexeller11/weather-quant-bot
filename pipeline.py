"""
Pipeline Engine do Quant Analytics.

Responsável por executar módulos
na ordem correta.

Cada pipeline recebe:

TradeDataset

↓

retorna dict
"""

from dataclasses import dataclass
from typing import Callable, List


@dataclass
class Pipeline:

    name: str

    execute: Callable

    enabled: bool = True


class PipelineEngine:

    def __init__(self):

        self._pipelines: List[Pipeline] = []

    def register(self, name, func):

        self._pipelines.append(

            Pipeline(

                name=name,

                execute=func

            )

        )

    def run(self, dataset):

        result = {}

        for pipeline in self._pipelines:

            if not pipeline.enabled:

                continue

            result[pipeline.name] = pipeline.execute(dataset)

        return result


pipeline = PipelineEngine()
