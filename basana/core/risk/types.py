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
import dataclasses
import datetime
import enum

from basana.core.pair import Pair


class DeploymentMode(enum.Enum):
    """Controls how the risk manager responds to limit breaches."""

    #: Log violations but pass all signals through.
    MONITOR = "monitor"
    #: Block violating signals.
    PAPER = "paper"
    #: Block violations and engage kill switch on critical breaches.
    LIVE = "live"


@dataclasses.dataclass(frozen=True)
class PositionSnapshot:
    """A point-in-time snapshot of a single position."""

    #: The trading pair.
    pair: Pair
    #: Signed quantity (positive = long, negative = short).
    signed_qty: Decimal
    #: Average entry price.
    avg_entry_price: Decimal
    #: Last known mark/market price.
    current_price: Decimal
    #: Unrealized P&L in quote currency.
    unrealized_pnl: Decimal
    #: Absolute notional value (|signed_qty * current_price|).
    notional_value: Decimal


@dataclasses.dataclass(frozen=True)
class PortfolioSnapshot:
    """A point-in-time snapshot of the entire portfolio."""

    #: When this snapshot was taken.
    when: datetime.datetime
    #: Position snapshots keyed by pair.
    positions: Dict[Pair, PositionSnapshot]
    #: Total equity (cash + unrealized P&L).
    total_equity: Decimal
    #: Sum of absolute notional values across all positions.
    gross_exposure: Decimal
    #: Net long minus short notional value.
    net_exposure: Decimal
    #: Realized P&L for the current day.
    realized_pnl_today: Decimal
    #: Total unrealized P&L.
    unrealized_pnl: Decimal


@dataclasses.dataclass(frozen=True)
class RiskCheckResult:
    """Result of a risk limit check."""

    #: Whether the signal is approved.
    approved: bool
    #: Human-readable reason if rejected or adjusted.
    reason: Optional[str] = None
