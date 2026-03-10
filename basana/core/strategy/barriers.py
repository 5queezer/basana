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
import datetime
import logging

from basana.core import dt, logs
from basana.core.pair import Pair
from basana.core.strategy.types import BarrierConfig, BarrierResult, ExitReason


logger = logging.getLogger(__name__)


class TripleBarrier:
    """Triple-barrier exit framework for a single position.

    Checks price against stop loss, take profit, and time barriers. Supports
    trailing stops, break-even arming, and partial take profit.

    :param pair: The trading pair.
    :param entry_price: The entry price.
    :param entry_dt: The entry datetime (timezone-aware).
    :param is_long: True for long, False for short.
    :param config: Barrier configuration.
    """

    def __init__(
        self,
        pair: Pair,
        entry_price: Decimal,
        entry_dt: datetime.datetime,
        is_long: bool,
        config: BarrierConfig,
    ):
        assert not dt.is_naive(entry_dt), f"{entry_dt} should have timezone information set"

        self._pair = pair
        self._entry_price = entry_price
        self._entry_dt = entry_dt
        self._is_long = is_long
        self._config = config

        self._peak_price = entry_price
        self._trough_price = entry_price
        self._break_even_armed = False
        self._partial_taken = False

    @property
    def pair(self) -> Pair:
        return self._pair

    @property
    def entry_price(self) -> Decimal:
        return self._entry_price

    @property
    def entry_dt(self) -> datetime.datetime:
        return self._entry_dt

    @property
    def is_long(self) -> bool:
        return self._is_long

    @property
    def config(self) -> BarrierConfig:
        return self._config

    @property
    def break_even_armed(self) -> bool:
        """Whether the break-even stop has been armed."""
        return self._break_even_armed

    @property
    def partial_taken(self) -> bool:
        """Whether partial take profit has been taken."""
        return self._partial_taken

    @property
    def peak_price(self) -> Decimal:
        """Highest price seen since entry (for longs) / lowest (for shorts)."""
        return self._peak_price if self._is_long else self._trough_price

    def check(self, current_price: Decimal, current_dt: datetime.datetime) -> BarrierResult:
        """Check all barriers against the current price and time.

        :param current_price: The current market price.
        :param current_dt: The current datetime (timezone-aware).
        :returns: A :class:`BarrierResult` indicating if any barrier was hit.
        """
        assert not dt.is_naive(current_dt), f"{current_dt} should have timezone information set"

        # Update peak/trough tracking.
        if current_price > self._peak_price:
            self._peak_price = current_price
        if current_price < self._trough_price:
            self._trough_price = current_price

        pnl_pct = self._calculate_pnl_pct(current_price)

        # 1. Check break-even arming.
        if not self._break_even_armed and self._config.break_even_pct is not None:
            if pnl_pct >= self._config.break_even_pct:
                self._break_even_armed = True
                logger.debug(
                    logs.StructuredMessage(
                        "Break-even armed",
                        pair=str(self._pair),
                        pnl_pct=str(pnl_pct),
                    )
                )

        # 2. Check partial take profit.
        if (
            not self._partial_taken
            and self._config.partial_take_profit_pct is not None
            and pnl_pct >= self._config.partial_take_profit_pct
        ):
            self._partial_taken = True
            return BarrierResult(
                hit=True,
                reason=ExitReason.PARTIAL_TAKE_PROFIT,
                exit_fraction=self._config.partial_take_profit_fraction,
            )

        # 3. Check take profit barrier.
        if self._config.take_profit_pct is not None and pnl_pct >= self._config.take_profit_pct:
            return BarrierResult(hit=True, reason=ExitReason.TAKE_PROFIT)

        # 4. Check break-even stop.
        if self._break_even_armed and pnl_pct <= Decimal(0):
            return BarrierResult(hit=True, reason=ExitReason.BREAK_EVEN_STOP)

        # 5. Check trailing stop.
        if self._config.trailing_stop_pct is not None:
            trailing_pnl = self._calculate_trailing_pnl_pct(current_price)
            if trailing_pnl <= -self._config.trailing_stop_pct:
                return BarrierResult(hit=True, reason=ExitReason.TRAILING_STOP)

        # 6. Check stop loss barrier.
        if self._config.stop_loss_pct is not None and pnl_pct <= -self._config.stop_loss_pct:
            return BarrierResult(hit=True, reason=ExitReason.STOP_LOSS)

        # 7. Check time barrier.
        if self._config.time_limit is not None:
            elapsed = current_dt - self._entry_dt
            if elapsed >= self._config.time_limit:
                return BarrierResult(hit=True, reason=ExitReason.TIME_EXIT)

        return BarrierResult(hit=False)

    def _calculate_pnl_pct(self, current_price: Decimal) -> Decimal:
        """Calculate P&L percentage from entry."""
        if self._entry_price == 0:
            return Decimal(0)
        if self._is_long:
            return ((current_price - self._entry_price) / self._entry_price) * Decimal(100)
        else:
            return ((self._entry_price - current_price) / self._entry_price) * Decimal(100)

    def _calculate_trailing_pnl_pct(self, current_price: Decimal) -> Decimal:
        """Calculate P&L percentage from peak (for trailing stop)."""
        if self._is_long:
            if self._peak_price == 0:  # pragma: no cover
                return Decimal(0)
            return ((current_price - self._peak_price) / self._peak_price) * Decimal(100)
        else:
            if self._trough_price == 0:
                return Decimal(0)
            return ((self._trough_price - current_price) / self._trough_price) * Decimal(100)
