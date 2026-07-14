"""
Registro automático das métricas.
"""

from .registry import registry

from .finance import summary as finance_summary
from .statistics import summary as statistics_summary
from .performance import summary as performance_summary


registry.register(
    "finance",
    finance_summary,
    category="finance",
)

registry.register(
    "statistics",
    statistics_summary,
    category="statistics",
)

registry.register(
    "performance",
    performance_summary,
    category="performance",
)
