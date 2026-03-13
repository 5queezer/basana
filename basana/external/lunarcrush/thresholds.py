from dataclasses import dataclass, field
from typing import List


@dataclass
class SignalThresholds:
    coins: List[str] = field(default_factory=lambda: ["BTC", "ETH"])
    galaxy_score_min: float = 65.0
    social_dominance_spike: float = 2.0
    alt_rank_max: int = 20
    price_change_min: float = 0.0
