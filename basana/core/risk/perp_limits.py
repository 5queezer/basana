# Basana
#
# Copyright 2026 Christian Pojoni
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from decimal import Decimal
from typing import Dict, Optional

from basana.core import enums
from basana.core.event_sources.trading_signal import BaseTradingSignal
from basana.core.pair import Pair
from basana.core.risk.limits import RiskLimit
from basana.core.risk.types import PortfolioSnapshot, RiskCheckResult


class MaxLeverageLimit(RiskLimit):
    """Rejects signals that would open positions when portfolio leverage is too high.

    Portfolio leverage is calculated as ``gross_exposure / total_equity``.

    :param max_leverage: Maximum allowed leverage multiplier (e.g. ``Decimal("10")``).
    """

    def __init__(self, max_leverage: Decimal):
        assert max_leverage > 0, "max_leverage must be positive"
        self._max_leverage = max_leverage

    def check(
        self, signal: BaseTradingSignal, portfolio: PortfolioSnapshot
    ) -> RiskCheckResult:
        if portfolio.total_equity <= 0:
            return RiskCheckResult(
                approved=False,
                reason="Cannot assess leverage: total equity is zero or negative",
            )
        current_leverage = portfolio.gross_exposure / portfolio.total_equity
        if current_leverage <= self._max_leverage:
            return RiskCheckResult(approved=True)

        # Allow signals that reduce/close positions.
        for _pair, position in signal.get_pairs():
            if position != enums.Position.NEUTRAL:
                return RiskCheckResult(
                    approved=False,
                    reason=f"Portfolio leverage {current_leverage:.1f}x exceeds "
                    f"max {self._max_leverage}x",
                )
        return RiskCheckResult(approved=True)


class LiquidationDistanceLimit(RiskLimit):
    """Rejects signals when any position is too close to liquidation.

    Requires the portfolio's ``positions`` to have ``liquidation_distance_pct`` available
    via the ``metadata`` dict on :class:`PositionSnapshot`.

    :param min_distance_pct: Minimum required distance to liquidation as a percentage.
    :param position_meta: Mapping of pair to liquidation distance percentage,
        updated externally from live position data.
    """

    def __init__(self, min_distance_pct: Decimal, position_meta: Optional[Dict[Pair, Decimal]] = None):
        assert min_distance_pct > 0, "min_distance_pct must be positive"
        self._min_distance_pct = min_distance_pct
        self._position_meta: Dict[Pair, Decimal] = position_meta or {}

    def update_liquidation_distance(self, pair: Pair, distance_pct: Decimal) -> None:
        """Update the liquidation distance for a pair.

        :param pair: The trading pair.
        :param distance_pct: Distance to liquidation as a percentage.
        """
        self._position_meta[pair] = distance_pct

    def remove_pair(self, pair: Pair) -> None:
        """Remove a pair's liquidation data (e.g. when position is closed)."""
        self._position_meta.pop(pair, None)

    def check(
        self, signal: BaseTradingSignal, portfolio: PortfolioSnapshot
    ) -> RiskCheckResult:
        for pair, distance_pct in self._position_meta.items():
            if distance_pct < self._min_distance_pct:
                # Allow close/reduce signals even when close to liquidation.
                for sig_pair, position in signal.get_pairs():
                    if sig_pair == pair and position != enums.Position.NEUTRAL:
                        return RiskCheckResult(
                            approved=False,
                            reason=f"{pair} liquidation distance {distance_pct:.1f}% "
                            f"below minimum {self._min_distance_pct}%",
                        )
        return RiskCheckResult(approved=True)


class MarginUtilizationLimit(RiskLimit):
    """Rejects signals when margin utilization exceeds a threshold.

    Margin utilization = ``gross_exposure / total_equity * 100``.

    :param max_utilization_pct: Maximum margin utilization as a percentage (e.g. ``Decimal("80")``).
    """

    def __init__(self, max_utilization_pct: Decimal):
        assert max_utilization_pct > 0, "max_utilization_pct must be positive"
        self._max_utilization_pct = max_utilization_pct

    def check(
        self, signal: BaseTradingSignal, portfolio: PortfolioSnapshot
    ) -> RiskCheckResult:
        if portfolio.total_equity <= 0:
            return RiskCheckResult(
                approved=False,
                reason="Cannot assess margin utilization: total equity is zero or negative",
            )
        utilization = portfolio.gross_exposure / portfolio.total_equity * Decimal(100)
        if utilization <= self._max_utilization_pct:
            return RiskCheckResult(approved=True)

        for _pair, position in signal.get_pairs():
            if position != enums.Position.NEUTRAL:
                return RiskCheckResult(
                    approved=False,
                    reason=f"Margin utilization {utilization:.1f}% exceeds "
                    f"max {self._max_utilization_pct}%",
                )
        return RiskCheckResult(approved=True)
