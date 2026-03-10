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

from basana.core.pair import Pair


@dataclasses.dataclass(frozen=True)
class TradeRecord:
    """An immutable record of a completed trade (round-trip or partial)."""

    #: Unique trade ID.
    trade_id: str
    #: The trading pair.
    pair: Pair
    #: Entry datetime.
    entry_dt: datetime.datetime
    #: Exit datetime.
    exit_dt: datetime.datetime
    #: Signed entry quantity (positive = long, negative = short).
    signed_qty: Decimal
    #: Entry price.
    entry_price: Decimal
    #: Exit price.
    exit_price: Decimal
    #: Realized P&L in quote currency.
    realized_pnl: Decimal
    #: Return as a fraction (e.g. 0.05 = 5%).
    return_pct: Decimal
    #: Optional reason code for the trade (e.g. "signal", "stop_loss", "take_profit", "time_exit").
    reason: Optional[str] = None


@dataclasses.dataclass(frozen=True)
class EquitySnapshot:
    """A point-in-time equity measurement."""

    #: When this snapshot was taken.
    when: datetime.datetime
    #: Total equity (cash + unrealized P&L).
    equity: Decimal


@dataclasses.dataclass(frozen=True)
class PerformanceMetrics:
    """Calculated performance metrics over a period."""

    #: Total number of trades.
    total_trades: int
    #: Number of winning trades.
    winning_trades: int
    #: Number of losing trades.
    losing_trades: int
    #: Win rate as a fraction (0-1).
    win_rate: Decimal
    #: Total realized P&L.
    total_pnl: Decimal
    #: Average P&L per trade.
    avg_pnl: Decimal
    #: Profit factor (gross profit / gross loss). None if no losses.
    profit_factor: Optional[Decimal]
    #: Expectancy (avg_win * win_rate - avg_loss * loss_rate).
    expectancy: Decimal
    #: Maximum drawdown as a fraction (0-1).
    max_drawdown: Decimal
    #: Annualized Sharpe ratio. None if insufficient data.
    sharpe_ratio: Optional[Decimal]
    #: Annualized Sortino ratio. None if insufficient data.
    sortino_ratio: Optional[Decimal]
    #: Calmar ratio (annualized return / max drawdown). None if max drawdown is zero.
    calmar_ratio: Optional[Decimal]
    #: Average winning trade P&L.
    avg_win: Decimal
    #: Average losing trade P&L.
    avg_loss: Decimal
