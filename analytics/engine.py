from analytics.dataset import build_dataset
from analytics.registry import registry
import analytics.register_metrics

dataset = build_dataset(bankroll)

analytics = registry.execute(dataset)
