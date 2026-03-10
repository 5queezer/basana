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
from typing import Dict, Optional, Sequence
import abc

from basana.core import enums
from basana.core.pair import Pair
from basana.core.event_sources.trading_signal import BaseTradingSignal
from basana.core.risk.types import PortfolioSnapshot, RiskCheckResult


class RiskLimit(abc.ABC):
    """Base class for risk limits.

    Subclass this to implement custom risk checks.
    """

    @abc.abstractmethod
    def check(
        self, signal: BaseTradingSignal, portfolio: PortfolioSnapshot
    ) -> RiskCheckResult:
        """Check whether the signal should be allowed given the current portfolio state.

        :param signal: The trading signal to evaluate.
        :param portfolio: The current portfolio snapshot.
        :returns: A :class:`RiskCheckResult` indicating approval or rejection.
        """
        raise NotImplementedError()


class MaxPositionsLimit(RiskLimit):
    """Rejects signals that would open a new position beyond a maximum count.

    Signals that close or reduce existing positions are always allowed.

    :param max_positions: Maximum number of concurrent positions.
    """

    def __init__(self, max_positions: int):
        assert max_positions > 0, "max_positions must be positive"
        self._max_positions = max_positions

    def check(
        self, signal: BaseTradingSignal, portfolio: PortfolioSnapshot
    ) -> RiskCheckResult:
        current_count = len(portfolio.positions)

        for pair, position in signal.get_pairs():
            is_new = pair not in portfolio.positions
            is_opening = position != enums.Position.NEUTRAL
            if is_new and is_opening and current_count >= self._max_positions:
                return RiskCheckResult(
                    approved=False,
                    reason=f"Max positions limit ({self._max_positions}) reached. "
                    f"Current: {current_count}",
                )
        return RiskCheckResult(approved=True)


class MaxGrossExposureLimit(RiskLimit):
    """Rejects signals that would push gross exposure above a cap.

    :param max_exposure: Maximum gross exposure as an absolute value in quote currency.
        If ``None``, this limit is not applied.
    :param max_exposure_pct: Maximum gross exposure as a percentage of total equity (e.g. 150 = 150%).
        If ``None``, this limit is not applied.
    """

    def __init__(
        self,
        max_exposure: Optional[Decimal] = None,
        max_exposure_pct: Optional[Decimal] = None,
    ):
        assert max_exposure is not None or max_exposure_pct is not None, (
            "At least one of max_exposure or max_exposure_pct must be set"
        )
        self._max_exposure = max_exposure
        self._max_exposure_pct = max_exposure_pct

    def check(
        self, signal: BaseTradingSignal, portfolio: PortfolioSnapshot
    ) -> RiskCheckResult:
        if self._max_exposure is not None and portfolio.gross_exposure > self._max_exposure:
            return RiskCheckResult(
                approved=False,
                reason=f"Gross exposure {portfolio.gross_exposure} exceeds "
                f"max {self._max_exposure}",
            )

        if self._max_exposure_pct is not None and portfolio.total_equity > 0:
            pct = (portfolio.gross_exposure / portfolio.total_equity) * Decimal(100)
            if pct > self._max_exposure_pct:
                return RiskCheckResult(
                    approved=False,
                    reason=f"Gross exposure {pct:.1f}% of equity exceeds "
                    f"max {self._max_exposure_pct}%",
                )

        return RiskCheckResult(approved=True)


class CorrelationBucketLimit(RiskLimit):
    """Limits total notional exposure within named correlation buckets.

    :param buckets: Mapping of bucket name to list of pairs in that bucket.
    :param max_per_bucket: Maximum notional exposure per bucket in quote currency.
    """

    def __init__(self, buckets: Dict[str, Sequence[Pair]], max_per_bucket: Decimal):
        assert max_per_bucket > 0, "max_per_bucket must be positive"
        self._pair_to_bucket: Dict[Pair, str] = {}
        for bucket_name, pairs in buckets.items():
            for p in pairs:
                self._pair_to_bucket[p] = bucket_name
        self._max_per_bucket = max_per_bucket

    def check(
        self, signal: BaseTradingSignal, portfolio: PortfolioSnapshot
    ) -> RiskCheckResult:
        # Calculate current exposure per bucket.
        bucket_exposure: Dict[str, Decimal] = {}
        for pair, pos in portfolio.positions.items():
            bucket = self._pair_to_bucket.get(pair)
            if bucket is not None:
                bucket_exposure[bucket] = bucket_exposure.get(bucket, Decimal(0)) + pos.notional_value

        # Check if any signal pair's bucket is already over limit.
        for pair, position in signal.get_pairs():
            if position == enums.Position.NEUTRAL:
                continue
            bucket = self._pair_to_bucket.get(pair)
            if bucket is not None:
                current = bucket_exposure.get(bucket, Decimal(0))
                if current >= self._max_per_bucket:
                    return RiskCheckResult(
                        approved=False,
                        reason=f"Correlation bucket '{bucket}' exposure "
                        f"{current} >= max {self._max_per_bucket}",
                    )

        return RiskCheckResult(approved=True)


class DailyLossCapLimit(RiskLimit):
    """Rejects risk-increasing signals when daily realized P&L exceeds a loss cap.

    :param max_loss: Maximum allowed daily loss as a positive value (e.g. Decimal("500") = $500 max loss).
    """

    def __init__(self, max_loss: Decimal):
        assert max_loss > 0, "max_loss must be positive"
        self._max_loss = max_loss

    def check(
        self, signal: BaseTradingSignal, portfolio: PortfolioSnapshot
    ) -> RiskCheckResult:
        daily_loss = portfolio.realized_pnl_today + portfolio.unrealized_pnl
        if daily_loss >= -self._max_loss:
            return RiskCheckResult(approved=True)

        # Check if signal would increase risk (open/add to position).
        for pair, position in signal.get_pairs():
            if position == enums.Position.NEUTRAL:
                continue
            # Opening new or adding to existing = risk-increasing.
            existing = portfolio.positions.get(pair)
            if existing is None:
                return RiskCheckResult(
                    approved=False,
                    reason=f"Daily loss cap breached. P&L: {daily_loss}, "
                    f"cap: -{self._max_loss}",
                )
            # Allowing signals that close/reduce.

        return RiskCheckResult(approved=True)


class PerTradeRiskSizer(RiskLimit):
    """Sizes positions as a fixed fraction of equity.

    This limit always approves signals but attaches sizing metadata.
    Downstream position managers should read the ``risk_sized_pct`` attribute
    from the signal to determine position size.

    :param risk_pct: Percentage of equity to risk per trade (e.g. Decimal("1") = 1%).
    """

    def __init__(self, risk_pct: Decimal):
        assert risk_pct > 0, "risk_pct must be positive"
        self._risk_pct = risk_pct

    def check(
        self, signal: BaseTradingSignal, portfolio: PortfolioSnapshot
    ) -> RiskCheckResult:
        # Attach sizing info to the signal for downstream consumption.
        if portfolio.total_equity > 0:
            signal.risk_sized_pct = self._risk_pct  # type: ignore[attr-defined]
            signal.risk_sized_amount = portfolio.total_equity * self._risk_pct / Decimal(100)  # type: ignore[attr-defined]
        return RiskCheckResult(approved=True)
