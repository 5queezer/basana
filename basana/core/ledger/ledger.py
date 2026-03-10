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
from typing import Dict, List, Optional, Sequence
import collections
import datetime
import logging
import uuid

from basana.core import dt, logs
from basana.core.pair import Pair
from basana.core.ledger.metrics import calculate_metrics
from basana.core.ledger.types import EquitySnapshot, PerformanceMetrics, TradeRecord


logger = logging.getLogger(__name__)


class _OpenPosition:
    def __init__(self, pair: Pair, signed_qty: Decimal, entry_price: Decimal, entry_dt: datetime.datetime):
        self.pair = pair
        self.signed_qty = signed_qty
        self.avg_entry_price = entry_price
        self.entry_dt = entry_dt
        self.current_price = entry_price

    @property
    def unrealized_pnl(self) -> Decimal:
        return (self.current_price - self.avg_entry_price) * self.signed_qty


class TradingLedger:
    """Paper trading ledger that records fills, tracks equity, and produces analytics.

    :param initial_cash: Starting cash balance in quote currency.
    :param equity_snapshot_interval: Minimum time between automatic equity snapshots.
        If ``None``, snapshots are only taken when explicitly requested or on fills.
    """

    def __init__(
        self,
        initial_cash: Decimal = Decimal(0),
        equity_snapshot_interval: Optional[datetime.timedelta] = None,
    ):
        self._initial_cash = initial_cash
        self._cash = initial_cash
        self._positions: Dict[Pair, _OpenPosition] = {}
        self._trades: List[TradeRecord] = []
        self._equity_curve: List[EquitySnapshot] = []
        self._snapshot_interval = equity_snapshot_interval
        self._last_snapshot_dt: Optional[datetime.datetime] = None
        self._daily_pnl: Dict[datetime.date, Decimal] = collections.defaultdict(Decimal)
        self._weekly_pnl: Dict[str, Decimal] = collections.defaultdict(Decimal)  # ISO week key

    def record_fill(
        self,
        pair: Pair,
        signed_qty: Decimal,
        fill_price: Decimal,
        when: datetime.datetime,
        reason: Optional[str] = None,
    ) -> Optional[TradeRecord]:
        """Record an order fill. Returns a TradeRecord if a position was closed/reduced.

        :param pair: The trading pair.
        :param signed_qty: Signed fill quantity (positive = buy, negative = sell).
        :param fill_price: The fill price.
        :param when: Fill datetime (timezone-aware).
        :param reason: Optional reason code for the trade.
        :returns: A :class:`TradeRecord` if a position was closed or reduced, else None.
        """
        assert not dt.is_naive(when), f"{when} should have timezone information set"

        trade_record = None
        pos = self._positions.get(pair)

        if pos is None:
            # Opening a new position.
            self._positions[pair] = _OpenPosition(pair, signed_qty, fill_price, when)
        elif pos.signed_qty * signed_qty > 0:
            # Adding to the same side.
            total_cost = abs(pos.signed_qty) * pos.avg_entry_price + abs(signed_qty) * fill_price
            pos.signed_qty += signed_qty
            pos.avg_entry_price = total_cost / abs(pos.signed_qty)
        else:
            # Reducing or closing or flipping.
            closed_qty = min(abs(signed_qty), abs(pos.signed_qty))
            if pos.signed_qty > 0:
                realized = (fill_price - pos.avg_entry_price) * closed_qty
            else:
                realized = (pos.avg_entry_price - fill_price) * closed_qty

            entry_cost = pos.avg_entry_price * closed_qty
            return_pct = realized / entry_cost if entry_cost != 0 else Decimal(0)

            trade_record = TradeRecord(
                trade_id=uuid.uuid4().hex[:12],
                pair=pair,
                entry_dt=pos.entry_dt,
                exit_dt=when,
                signed_qty=pos.signed_qty if closed_qty == abs(pos.signed_qty) else (
                    Decimal(closed_qty) if pos.signed_qty > 0 else Decimal(-closed_qty)
                ),
                entry_price=pos.avg_entry_price,
                exit_price=fill_price,
                realized_pnl=realized,
                return_pct=return_pct,
                reason=reason,
            )
            self._trades.append(trade_record)
            self._cash += realized

            # Track daily/weekly P&L.
            trade_date = when.date()
            self._daily_pnl[trade_date] += realized
            iso_year, iso_week, _ = trade_date.isocalendar()
            self._weekly_pnl[f"{iso_year}-W{iso_week:02d}"] += realized

            logger.debug(
                logs.StructuredMessage(
                    "Trade closed",
                    pair=str(pair),
                    pnl=str(realized),
                    return_pct=f"{return_pct:.4f}",
                    reason=reason,
                )
            )

            new_qty = pos.signed_qty + signed_qty
            if new_qty == Decimal(0):
                del self._positions[pair]
            elif pos.signed_qty * new_qty < 0:
                # Flipped sides.
                self._positions[pair] = _OpenPosition(pair, new_qty, fill_price, when)
            else:
                pos.signed_qty = new_qty

        # Update price and take snapshot.
        if pair in self._positions:
            self._positions[pair].current_price = fill_price
        self._maybe_snapshot(when)

        return trade_record

    def update_price(self, pair: Pair, price: Decimal, when: Optional[datetime.datetime] = None) -> None:
        """Update the market price for a pair.

        :param pair: The trading pair.
        :param price: The current market price.
        :param when: Optional datetime for triggering equity snapshots.
        """
        pos = self._positions.get(pair)
        if pos is not None:
            pos.current_price = price
        if when is not None:
            self._maybe_snapshot(when)

    def take_snapshot(self, when: datetime.datetime) -> EquitySnapshot:
        """Take an equity snapshot at the given time.

        :param when: The snapshot datetime (timezone-aware).
        :returns: The equity snapshot.
        """
        assert not dt.is_naive(when), f"{when} should have timezone information set"

        equity = self._cash + sum((p.unrealized_pnl for p in self._positions.values()), Decimal(0))
        snap = EquitySnapshot(when=when, equity=equity)
        self._equity_curve.append(snap)
        self._last_snapshot_dt = when
        return snap

    @property
    def trades(self) -> Sequence[TradeRecord]:
        """All completed trade records."""
        return self._trades

    @property
    def equity_curve(self) -> Sequence[EquitySnapshot]:
        """All equity snapshots taken so far."""
        return self._equity_curve

    @property
    def cash(self) -> Decimal:
        """Current cash balance."""
        return self._cash

    @property
    def open_positions(self) -> Dict[Pair, Decimal]:
        """Current open positions as {pair: signed_qty}."""
        return {pair: pos.signed_qty for pair, pos in self._positions.items()}

    def get_equity(self) -> Decimal:
        """Current total equity (cash + unrealized P&L)."""
        return self._cash + sum((p.unrealized_pnl for p in self._positions.values()), Decimal(0))

    def get_unrealized_pnl(self) -> Decimal:
        """Total unrealized P&L across all open positions."""
        return sum((p.unrealized_pnl for p in self._positions.values()), Decimal(0))

    def get_daily_pnl(self) -> Dict[datetime.date, Decimal]:
        """Realized P&L by date."""
        return dict(self._daily_pnl)

    def get_weekly_pnl(self) -> Dict[str, Decimal]:
        """Realized P&L by ISO week (e.g. '2026-W01')."""
        return dict(self._weekly_pnl)

    def calculate_metrics(self, periods_per_year: int = 252) -> PerformanceMetrics:
        """Calculate performance metrics from all recorded trades and equity curve.

        :param periods_per_year: Number of periods per year for annualization.
        :returns: A :class:`PerformanceMetrics` instance.
        """
        return calculate_metrics(self._trades, self._equity_curve, periods_per_year)

    def _maybe_snapshot(self, when: datetime.datetime) -> None:
        if self._snapshot_interval is None:
            return
        if self._last_snapshot_dt is None or (when - self._last_snapshot_dt) >= self._snapshot_interval:
            self.take_snapshot(when)
