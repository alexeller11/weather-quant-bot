"""
analytics.manager

Interface pública do Quant Intelligence Engine.

Uso:

    from analytics.manager import AnalyticsManager

    manager = AnalyticsManager()

    manager.update(bankroll)

    manager.save()

    report = manager.report()

    health = manager.health()

"""

from __future__ import annotations

from typing import Dict, Optional

from .dataset import build_dataset
from .registry import registry
from .health import evaluate, to_dict
from .storage import (
    save_analytics,
    save_health,
)

# força o registro automático
from . import register_metrics  # noqa: F401


class AnalyticsManager:

    def __init__(self):

        self.dataset = None

        self.snapshot = {}

        self.health_report = None

    # --------------------------------------------------

    def update(self, bankroll: Dict):

        """
        Recalcula todo o Analytics.
        """

        self.dataset = build_dataset(bankroll)

        self.snapshot = registry.execute(self.dataset)

        #
        # Junta todos os módulos
        #

        metrics = {}

        metrics.update(

            self.snapshot.get("finance", {})

        )

        metrics.update(

            self.snapshot.get("statistics", {})

        )

        #
        # número de trades
        #

        metrics["trades"] = self.dataset.trades

        self.health_report = evaluate(metrics)

        return self.snapshot

    # --------------------------------------------------

    def analytics(self):

        return self.snapshot

    # --------------------------------------------------

    def health(self):

        if self.health_report is None:

            return {}

        return to_dict(

            self.health_report

        )

    # --------------------------------------------------

    def report(self):

        return {

            "analytics": self.analytics(),

            "health": self.health(),

        }

    # --------------------------------------------------

    def save(self):

        if self.snapshot:

            save_analytics(

                self.snapshot

            )

        if self.health_report:

            save_health(

                to_dict(

                    self.health_report

                )

            )

    # --------------------------------------------------

    def run(self, bankroll):

        """
        Pipeline completo.

        update

            ↓

        save

            ↓

        return report
        """

        self.update(bankroll)

        self.save()

        return self.report()


#
# Singleton
#

analytics_manager = AnalyticsManager()
