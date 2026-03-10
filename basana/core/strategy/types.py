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
from typing import Optional
import dataclasses
import datetime
import enum


class ExitReason(enum.Enum):
    """Reason for exiting a position."""

    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    TIME_EXIT = "time_exit"
    TRAILING_STOP = "trailing_stop"
    BREAK_EVEN_STOP = "break_even_stop"
    SIGNAL = "signal"
    PARTIAL_TAKE_PROFIT = "partial_take_profit"


class BarrierStatus(enum.Enum):
    """Status of a barrier check."""

    OPEN = "open"
    HIT = "hit"


@dataclasses.dataclass(frozen=True)
class BarrierConfig:
    """Configuration for the triple-barrier framework.

    :param stop_loss_pct: Stop loss as a positive percentage (e.g. Decimal("2") = 2%).
    :param take_profit_pct: Take profit as a positive percentage.
    :param time_limit: Maximum time to hold a position.
    :param trailing_stop_pct: Trailing stop as a positive percentage from peak. If set, replaces
        the fixed stop loss once the position is profitable by at least this amount.
    :param break_even_pct: Once the position is profitable by this percentage, move stop to entry.
    :param partial_take_profit_pct: Take partial profit at this percentage gain.
    :param partial_take_profit_fraction: Fraction of position to close at partial take profit (0-1).
    """

    stop_loss_pct: Optional[Decimal] = None
    take_profit_pct: Optional[Decimal] = None
    time_limit: Optional[datetime.timedelta] = None
    trailing_stop_pct: Optional[Decimal] = None
    break_even_pct: Optional[Decimal] = None
    partial_take_profit_pct: Optional[Decimal] = None
    partial_take_profit_fraction: Decimal = Decimal("0.5")


@dataclasses.dataclass(frozen=True)
class BarrierResult:
    """Result of a barrier check."""

    #: Whether a barrier was hit.
    hit: bool
    #: The exit reason if hit.
    reason: Optional[ExitReason] = None
    #: Fraction of position to exit (1 = full, < 1 = partial).
    exit_fraction: Decimal = Decimal("1")
