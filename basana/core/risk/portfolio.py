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
import logging

from basana.core import dt, logs
from basana.core.pair import Pair
from basana.core.risk.types import PortfolioSnapshot, PositionSnapshot


logger = logging.getLogger(__name__)


@dataclasses.dataclass
class _MutablePosition:
    pair: Pair
    signed_qty: Decimal = Decimal(0)
    avg_entry_price: Decimal = Decimal(0)
    current_price: Decimal = Decimal(0)
    realized_pnl: Decimal = Decimal(0)


class PortfolioTracker:
    """Tracks portfolio state from order fills and price updates.

    :param initial_cash: Starting cash balance in quote currency.
    """

    def __init__(self, initial_cash: Decimal = Decimal(0)):
        self._positions: Dict[Pair, _MutablePosition] = {}
        self._initial_cash = initial_cash
        self._cash = initial_cash
        self._realized_pnl_today = Decimal(0)
        self._total_realized_pnl = Decimal(0)
        self._daily_reset_date: Optional[datetime.date] = None

    def _get_or_create_position(self, pair: Pair) -> _MutablePosition:
        if pair not in self._positions:
            self._positions[pair] = _MutablePosition(pair=pair)
        return self._positions[pair]

    def _maybe_reset_daily_pnl(self, when: datetime.datetime) -> None:
        current_date = when.date()
        if self._daily_reset_date is None or current_date > self._daily_reset_date:
            self._daily_reset_date = current_date
            self._realized_pnl_today = Decimal(0)

    def update_price(self, pair: Pair, price: Decimal) -> None:
        """Update the current market price for a pair.

        :param pair: The trading pair.
        :param price: The current market price.
        """
        pos = self._get_or_create_position(pair)
        pos.current_price = price

    def record_fill(
        self,
        pair: Pair,
        signed_qty: Decimal,
        fill_price: Decimal,
        when: datetime.datetime,
    ) -> None:
        """Record an order fill.

        :param pair: The trading pair.
        :param signed_qty: Signed fill quantity (positive = buy, negative = sell).
        :param fill_price: The price at which the fill occurred.
        :param when: The datetime of the fill. Must be timezone-aware.
        """
        assert not dt.is_naive(when), f"{when} should have timezone information set"

        self._maybe_reset_daily_pnl(when)

        pos = self._get_or_create_position(pair)
        old_qty = pos.signed_qty
        new_qty = old_qty + signed_qty

        # Calculate realized P&L if reducing or closing a position.
        realized = Decimal(0)
        if old_qty != Decimal(0) and ((old_qty > 0 and signed_qty < 0) or (old_qty < 0 and signed_qty > 0)):
            # Closing/reducing: the closed portion's P&L.
            closed_qty = min(abs(signed_qty), abs(old_qty))
            if old_qty > 0:
                realized = (fill_price - pos.avg_entry_price) * closed_qty
            else:
                realized = (pos.avg_entry_price - fill_price) * closed_qty

        self._realized_pnl_today += realized
        self._total_realized_pnl += realized
        self._cash += realized

        # Update average entry price.
        if old_qty == Decimal(0):
            # Opening a fresh position.
            pos.avg_entry_price = fill_price
        elif old_qty * signed_qty > 0:
            # Adding to the same side.
            total_cost = abs(old_qty) * pos.avg_entry_price + abs(signed_qty) * fill_price
            pos.avg_entry_price = total_cost / (abs(old_qty) + abs(signed_qty))
        elif new_qty != Decimal(0) and old_qty * new_qty < 0:
            # Flipped sides: new avg entry is the fill price for the new side.
            pos.avg_entry_price = fill_price
        elif new_qty == Decimal(0):
            pos.avg_entry_price = Decimal(0)
        # Else: partial close, keep the existing avg entry price.

        pos.signed_qty = new_qty
        pos.current_price = fill_price

        logger.debug(
            logs.StructuredMessage(
                "Fill recorded",
                pair=str(pair),
                signed_qty=str(signed_qty),
                fill_price=str(fill_price),
                position_qty=str(new_qty),
                realized_pnl=str(realized),
            )
        )

    def snapshot(self, when: datetime.datetime) -> PortfolioSnapshot:
        """Return a frozen snapshot of the current portfolio state.

        :param when: The datetime for the snapshot. Must be timezone-aware.
        :returns: A frozen :class:`PortfolioSnapshot`.
        """
        assert not dt.is_naive(when), f"{when} should have timezone information set"

        self._maybe_reset_daily_pnl(when)

        positions: Dict[Pair, PositionSnapshot] = {}
        total_unrealized = Decimal(0)
        gross_exposure = Decimal(0)
        net_exposure = Decimal(0)

        for pair, pos in self._positions.items():
            if pos.signed_qty == Decimal(0):
                continue

            unrealized = (pos.current_price - pos.avg_entry_price) * pos.signed_qty
            notional = abs(pos.signed_qty * pos.current_price)
            total_unrealized += unrealized
            gross_exposure += notional
            net_exposure += pos.signed_qty * pos.current_price

            positions[pair] = PositionSnapshot(
                pair=pair,
                signed_qty=pos.signed_qty,
                avg_entry_price=pos.avg_entry_price,
                current_price=pos.current_price,
                unrealized_pnl=unrealized,
                notional_value=notional,
            )

        total_equity = self._cash + total_unrealized

        return PortfolioSnapshot(
            when=when,
            positions=positions,
            total_equity=total_equity,
            gross_exposure=gross_exposure,
            net_exposure=net_exposure,
            realized_pnl_today=self._realized_pnl_today,
            unrealized_pnl=total_unrealized,
        )

    @property
    def cash(self) -> Decimal:
        """The current cash balance."""
        return self._cash

    @property
    def realized_pnl_today(self) -> Decimal:
        """Realized P&L for the current day."""
        return self._realized_pnl_today

    @property
    def total_realized_pnl(self) -> Decimal:
        """Total realized P&L since inception."""
        return self._total_realized_pnl
