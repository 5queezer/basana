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
from typing import Any, Awaitable, Callable, List, Optional
import datetime
import logging

from basana.core import bar, dispatcher, event, logs
from basana.core.event_sources.trading_signal import BaseTradingSignal
from basana.core.pair import Pair
from basana.core.risk.limits import RiskLimit
from basana.core.risk.portfolio import PortfolioTracker
from basana.core.risk.types import DeploymentMode


logger = logging.getLogger(__name__)


class RiskManager(event.FifoQueueEventSource):
    """Portfolio-level risk manager that filters trading signals through configurable limits.

    The risk manager sits between strategy signal sources and the position manager.
    It checks each incoming signal against risk limits and only forwards approved signals.

    :param dispatcher: The event dispatcher.
    :param portfolio: The portfolio tracker for state.
    :param limits: List of risk limits to check, in order.
    :param mode: Deployment mode controlling how breaches are handled.
    """

    def __init__(
        self,
        event_dispatcher: dispatcher.EventDispatcher,
        portfolio: PortfolioTracker,
        limits: Optional[List[RiskLimit]] = None,
        mode: DeploymentMode = DeploymentMode.LIVE,
    ):
        super().__init__()
        self._dispatcher = event_dispatcher
        self._portfolio = portfolio
        self._limits = limits or []
        self._mode = mode
        self._kill_switch_active = False
        self._kill_switch_reason: Optional[str] = None

    @property
    def kill_switch_active(self) -> bool:
        """True if the kill switch has been activated."""
        return self._kill_switch_active

    @property
    def kill_switch_reason(self) -> Optional[str]:
        """The reason the kill switch was activated, or None."""
        return self._kill_switch_reason

    @property
    def mode(self) -> DeploymentMode:
        """The current deployment mode."""
        return self._mode

    @property
    def portfolio(self) -> PortfolioTracker:
        """The portfolio tracker."""
        return self._portfolio

    def set_mode(self, mode: DeploymentMode) -> None:
        """Change the deployment mode at runtime.

        :param mode: The new deployment mode.
        """
        old_mode = self._mode
        self._mode = mode
        logger.info(logs.StructuredMessage("Deployment mode changed", old=old_mode.value, new=mode.value))

    def activate_kill_switch(self, reason: str) -> None:
        """Activate the kill switch, blocking all new risk-increasing signals.

        :param reason: Human-readable reason for activation.
        """
        self._kill_switch_active = True
        self._kill_switch_reason = reason
        logger.warning(logs.StructuredMessage("Kill switch activated", reason=reason))

    def deactivate_kill_switch(self) -> None:
        """Deactivate the kill switch, resuming normal operation."""
        self._kill_switch_active = False
        self._kill_switch_reason = None
        logger.info("Kill switch deactivated")

    def subscribe_to_filtered_signals(
        self, event_handler: Callable[[BaseTradingSignal], Awaitable[Any]]
    ) -> None:
        """Register a handler for approved trading signals.

        :param event_handler: Async callable that receives approved signals.
        """
        self._dispatcher.subscribe(self, event_handler)  # type: ignore[arg-type]

    async def on_trading_signal(self, signal: BaseTradingSignal) -> None:
        """Process an incoming trading signal through risk limits.

        :param signal: The trading signal to evaluate.
        """
        when = signal.when
        snapshot = self._portfolio.snapshot(when)

        # Kill switch check.
        if self._kill_switch_active:
            if self._mode == DeploymentMode.MONITOR:
                logger.warning(
                    logs.StructuredMessage(
                        "Kill switch active (MONITOR mode, passing through)",
                        reason=self._kill_switch_reason,
                    )
                )
            else:
                logger.warning(
                    logs.StructuredMessage(
                        "Signal blocked by kill switch",
                        reason=self._kill_switch_reason,
                    )
                )
                return

        # Run each limit check.
        for limit in self._limits:
            result = limit.check(signal, snapshot)
            if not result.approved:
                if self._mode == DeploymentMode.MONITOR:
                    logger.warning(
                        logs.StructuredMessage(
                            "Risk limit breached (MONITOR mode, passing through)",
                            limit=type(limit).__name__,
                            reason=result.reason,
                        )
                    )
                else:
                    logger.warning(
                        logs.StructuredMessage(
                            "Signal blocked by risk limit",
                            limit=type(limit).__name__,
                            reason=result.reason,
                        )
                    )
                    return

        # All checks passed: forward the signal.
        self.push(signal)

    async def on_bar_event(self, bar_event: bar.BarEvent) -> None:
        """Update portfolio prices from bar events.

        :param bar_event: The bar event with updated market data.
        """
        self._portfolio.update_price(bar_event.bar.pair, bar_event.bar.close)

    def record_fill(
        self,
        pair: Pair,
        signed_qty: Decimal,
        fill_price: Decimal,
        when: datetime.datetime,
    ) -> None:
        """Record an order fill in the portfolio tracker.

        :param pair: The trading pair.
        :param signed_qty: Signed fill quantity.
        :param fill_price: Fill price.
        :param when: Fill datetime (timezone-aware).
        """
        self._portfolio.record_fill(pair, signed_qty, fill_price, when)
