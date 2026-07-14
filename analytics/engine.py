
"""
analytics.engine

Orquestrador do Quant Intelligence Engine.
"""

from __future__ import annotations

from typing import Dict, Optional

from .manager import AnalyticsManager


def run(bankroll: Dict) -> Dict:
    """
    Executa todo o pipeline de analytics.

    Retorna:
        {
            "analytics": ...,
            "health": ...
        }
    """
    manager = AnalyticsManager()
    return manager.run(bankroll)


def update(bankroll: Dict) -> Dict:
    """
    Atualiza métricas sem persistir em disco.
    """
    manager = AnalyticsManager()
    manager.update(bankroll)
    return manager.report()


def save(bankroll: Dict) -> Dict:
    """
    Atualiza e salva analytics.
    """
    manager = AnalyticsManager()
    manager.update(bankroll)
    manager.save()
    return manager.report()


def report(bankroll: Dict) -> str:
    """
    Retorna relatório em texto.
    """
    manager = AnalyticsManager()
    manager.update(bankroll)
    return manager.report_text()


def report_markdown(bankroll: Dict) -> str:
    """
    Retorna relatório em Markdown.
    """
    manager = AnalyticsManager()
    manager.update(bankroll)
    return manager.report_markdown()


class AnalyticsEngine:
    """
    Interface OO opcional.
    """

    def __init__(self):
        self.manager = AnalyticsManager()

    def run(self, bankroll: Dict):
        return self.manager.run(bankroll)

    def update(self, bankroll: Dict):
        self.manager.update(bankroll)
        return self.manager.report()

    def save(self):
        self.manager.save()

    def analytics(self):
        return self.manager.analytics()

    def health(self):
        return self.manager.health()

    def report(self):
        return self.manager.report_text()

    def report_markdown(self):
        return self.manager.report_markdown()


engine = AnalyticsEngine()
