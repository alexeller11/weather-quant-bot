
"""
analytics.manager

Interface pública do Quant Intelligence Engine.
"""

from __future__ import annotations

from typing import Dict

from .dataset import build_dataset
from .registry import registry
from .health import evaluate, to_dict
from .reports import text as report_text, markdown as report_markdown
from .storage import save_analytics, save_health, load_analytics, load_health

from . import register_metrics  # noqa: F401


class AnalyticsManager:

    def __init__(self):
        self.dataset = None
        self.snapshot = {}
        self.health_report = None

    def update(self, bankroll: Dict):
        self.dataset = build_dataset(bankroll)
        self.snapshot = registry.execute(self.dataset)

        metrics = {}
        metrics.update(self.snapshot.get("finance", {}))
        metrics.update(self.snapshot.get("statistics", {}))
        metrics["trades"] = self.dataset.trades

        self.health_report = evaluate(metrics)
        return self.snapshot

    def analytics(self):
        return self.snapshot

    def health(self):
        return {} if self.health_report is None else to_dict(self.health_report)

    def report(self):
        return {
            "analytics": self.analytics(),
            "health": self.health(),
        }

    def report_text(self):
        return report_text(self.report())

    def report_markdown(self):
        return report_markdown(self.report())

    def save(self):
        if self.snapshot:
            save_analytics(self.snapshot)
        if self.health_report:
            save_health(to_dict(self.health_report))

    def load(self):
        self.snapshot = load_analytics() or {}
        return self.snapshot

    def load_health(self):
        return load_health() or {}

    def clear(self):
        self.dataset = None
        self.snapshot = {}
        self.health_report = None

    def run(self, bankroll: Dict):
        self.update(bankroll)
        self.save()
        return self.report()


analytics_manager = AnalyticsManager()
