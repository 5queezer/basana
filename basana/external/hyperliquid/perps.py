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
from typing import Any, Awaitable, Callable, List, Optional, cast
import dataclasses
import datetime
import logging

from basana.core import dispatcher
from basana.core.enums import OrderOperation
from . import client, helpers, websockets


logger = logging.getLogger(__name__)

FillEventHandler = Callable[[dict], Awaitable[Any]]


@dataclasses.dataclass(frozen=True)
class Position:
    """An open perpetuals position."""

    #: The coin (e.g. ``"ETH"``).
    coin: str
    #: Size — positive for long, negative for short.
    size: Decimal
    #: Average entry price in USD.
    entry_price: Decimal
    #: Unrealized P&L in USD.
    unrealized_pnl: Decimal
    #: Liquidation price in USD, or ``None`` if not applicable.
    liquidation_price: Optional[Decimal]
    #: Leverage multiplier.
    leverage: Decimal
    #: Margin used in USD.
    margin_used: Decimal
    #: Current mark price, or ``None`` if unknown.
    mark_price: Optional[Decimal] = None
    #: Cumulative funding paid (negative = received), or ``None`` if unknown.
    cumulative_funding: Optional[Decimal] = None

    @property
    def is_long(self) -> bool:
        """``True`` if the position is long."""
        return self.size > 0

    @property
    def is_short(self) -> bool:
        """``True`` if the position is short."""
        return self.size < 0

    @property
    def notional_value(self) -> Decimal:
        """Absolute notional value based on entry price."""
        return abs(self.size * self.entry_price)

    @property
    def return_on_equity(self) -> Optional[Decimal]:
        """Return on margin used, or ``None`` if margin is zero."""
        if self.margin_used == 0:
            return None
        return self.unrealized_pnl / self.margin_used

    @property
    def liquidation_distance_pct(self) -> Optional[Decimal]:
        """Distance to liquidation as a percentage of mark/entry price.

        Returns ``None`` if liquidation price or mark price is unknown.
        """
        if self.liquidation_price is None:
            return None
        ref_price = self.mark_price if self.mark_price is not None else self.entry_price
        if ref_price == 0:
            return None
        return abs(ref_price - self.liquidation_price) / ref_price * Decimal(100)


@dataclasses.dataclass(frozen=True)
class FillEvent:
    """A structured fill from the exchange."""

    #: Coin (e.g. ``"ETH"``).
    coin: str
    #: Order ID.
    oid: int
    #: ``True`` if buy side.
    is_buy: bool
    #: Fill size.
    size: Decimal
    #: Fill price.
    price: Decimal
    #: Fee paid (always positive).
    fee: Decimal
    #: Realized P&L from this fill (if closing/reducing a position).
    realized_pnl: Decimal
    #: When the fill occurred.
    when: datetime.datetime
    #: Whether this fill crossed the spread (taker) or rested (maker).
    is_maker: bool = False


@dataclasses.dataclass(frozen=True)
class FundingPayment:
    """A single funding rate payment record."""

    #: Coin (e.g. ``"ETH"``).
    coin: str
    #: Funding rate as a decimal (e.g. ``Decimal("0.0001")`` = 0.01%).
    rate: Decimal
    #: Payment amount in USD (negative = received by longs, positive = paid by longs).
    payment: Decimal
    #: Timestamp of the funding event.
    when: datetime.datetime


@dataclasses.dataclass(frozen=True)
class OrderInfo:
    """A placed or open order."""

    #: Order ID returned by the exchange.
    oid: int
    coin: str
    is_buy: bool
    size: Decimal
    limit_price: Optional[Decimal]
    filled: Decimal
    status: str


class Account:
    """Hyperliquid perpetuals account.

    Provides order placement, position queries, and real-time fill subscriptions.

    :param api_client: The REST API client.
    :param ws_client: The WebSocket client.
    """

    def __init__(
        self,
        api_client: client.APIClient,
        ws_client: websockets.WebSocketClient,
        event_dispatcher: dispatcher.EventDispatcher,
    ):
        self._cli = api_client
        self._ws = ws_client
        self._dispatcher = event_dispatcher

    # ------------------------------------------------------------------
    # Account state
    # ------------------------------------------------------------------

    async def get_positions(self) -> List[Position]:
        """Return all open perpetuals positions.

        Each position includes mark price when available from the exchange mid-price feed.
        """
        state = await self._cli.get_user_state()
        # Fetch current mid prices to enrich positions with mark price.
        try:
            mids = await self._cli.get_all_mids()
        except Exception:
            mids = {}
        positions = []
        for p in state.get("assetPositions", []):
            pos = p.get("position", {})
            if pos.get("szi") == "0":
                continue
            coin = pos["coin"]
            mark = Decimal(mids[coin]) if coin in mids else None
            cum_funding_raw = pos.get("cumFunding", {})
            cum_funding = None
            if "sinceOpen" in cum_funding_raw:
                cum_funding = Decimal(str(cum_funding_raw["sinceOpen"]))
            positions.append(Position(
                coin=coin,
                size=Decimal(pos["szi"]),
                entry_price=Decimal(pos["entryPx"]) if pos.get("entryPx") else Decimal(0),
                unrealized_pnl=Decimal(pos.get("unrealizedPnl", "0")),
                liquidation_price=Decimal(pos["liquidationPx"]) if pos.get("liquidationPx") else None,
                leverage=Decimal(str(pos.get("leverage", {}).get("value", 1))),
                margin_used=Decimal(pos.get("marginUsed", "0")),
                mark_price=mark,
                cumulative_funding=cum_funding,
            ))
        return positions

    async def get_balance(self) -> Decimal:
        """Return the account equity (total margin balance) in USD."""
        state = await self._cli.get_user_state()
        return Decimal(state.get("marginSummary", {}).get("accountValue", "0"))

    async def get_open_orders(self) -> List[OrderInfo]:
        """Return all open orders."""
        raw = await self._cli.get_open_orders()
        return [
            OrderInfo(
                oid=o["oid"],
                coin=o["coin"],
                is_buy=o["side"] == "B",
                size=Decimal(o["sz"]),
                limit_price=Decimal(o["limitPx"]) if o.get("limitPx") else None,
                filled=Decimal(o.get("filledSz", "0")),
                status=o.get("orderType", "unknown"),
            )
            for o in raw
        ]

    # ------------------------------------------------------------------
    # Order management
    # ------------------------------------------------------------------

    async def market_open(
        self, coin: str, operation: OrderOperation, size: Decimal, slippage: float = 0.01
    ) -> OrderInfo:
        """Open a position at market price.

        :param coin: e.g. ``"ETH"``
        :param operation: ``OrderOperation.BUY`` for long, ``OrderOperation.SELL`` for short.
        :param size: Position size in base asset units.
        :param slippage: Maximum acceptable slippage (default 1 %).
        """
        is_buy = operation == OrderOperation.BUY
        result = await self._cli.market_open(coin, is_buy, float(size), slippage)
        return self._parse_order_result(result, coin, is_buy=is_buy)

    async def market_close(self, coin: str, size: Optional[Decimal] = None, slippage: float = 0.01) -> OrderInfo:
        """Close a position at market price.

        :param coin: e.g. ``"ETH"``
        :param size: Amount to close. ``None`` closes the entire position.
        :param slippage: Maximum acceptable slippage (default 1 %).
        """
        result = await self._cli.market_close(coin, float(size) if size else None, slippage)
        return self._parse_order_result(result, coin)

    async def limit_order(
        self,
        coin: str,
        operation: OrderOperation,
        size: Decimal,
        limit_price: Decimal,
        reduce_only: bool = False,
    ) -> OrderInfo:
        """Place a limit order.

        :param coin: e.g. ``"ETH"``
        :param operation: ``OrderOperation.BUY`` or ``OrderOperation.SELL``.
        :param size: Size in base asset units.
        :param limit_price: Limit price in USD.
        :param reduce_only: If ``True``, the order can only reduce an existing position.
        """
        is_buy = operation == OrderOperation.BUY
        result = await self._cli.limit_order(coin, is_buy, float(size), float(limit_price), reduce_only)
        return self._parse_order_result(result, coin, is_buy=is_buy)

    async def cancel_order(self, coin: str, oid: int) -> None:
        """Cancel order ``oid`` for ``coin``."""
        await self._cli.cancel_order(coin, oid)

    async def set_leverage(self, coin: str, leverage: int, is_cross: bool = True) -> None:
        """Set leverage for ``coin``.

        :param coin: e.g. ``"ETH"``
        :param leverage: Leverage multiplier.
        :param is_cross: ``True`` for cross margin, ``False`` for isolated.
        """
        await self._cli.set_leverage(coin, leverage, is_cross)

    # ------------------------------------------------------------------
    # Funding & analytics
    # ------------------------------------------------------------------

    async def get_funding_history(
        self, coin: str, start_time: datetime.datetime, end_time: Optional[datetime.datetime] = None
    ) -> List[FundingPayment]:
        """Return funding rate history for ``coin``.

        :param coin: e.g. ``"ETH"``
        :param start_time: Start datetime (timezone-aware).
        :param end_time: End datetime (timezone-aware). ``None`` for now.
        """
        start_ms = int(start_time.timestamp() * 1000)
        end_ms = int(end_time.timestamp() * 1000) if end_time else None
        raw = await self._cli.get_funding_history(coin, start_ms, end_ms)
        return [self._parse_funding(coin, f) for f in raw]

    async def get_fills(self, start_time: datetime.datetime) -> List[FillEvent]:
        """Return trade fills since ``start_time``.

        :param start_time: Start datetime (timezone-aware).
        """
        start_ms = int(start_time.timestamp() * 1000)
        raw = await self._cli.get_user_fills(start_ms)
        return [self._parse_fill(f) for f in raw]

    async def get_margin_summary(self) -> dict:
        """Return the full margin summary from the exchange.

        The returned dict includes ``accountValue``, ``totalMarginUsed``,
        ``totalNtlPos``, ``totalRawUsd``, and ``withdrawable``.
        """
        state = await self._cli.get_user_state()
        return state.get("marginSummary", {})

    # ------------------------------------------------------------------
    # Real-time events
    # ------------------------------------------------------------------

    def subscribe_to_fill_events(self, handler: FillEventHandler) -> None:
        """Subscribe to real-time fill events via WebSocket.

        :param handler: Async callable receiving a fill event dict.
        """
        if not self._cli.address:
            raise client.Error("Private key required to subscribe to fill events")

        channel = websockets._user_fills_channel(self._cli.address)
        event_source = self._ws.get_channel_event_source(channel)
        if event_source is None:
            event_source = websockets.RawEventSource(producer=self._ws)
            self._ws.set_channel_event_source(channel, event_source)
        self._dispatcher.subscribe(event_source, cast(dispatcher.EventHandler, handler))

    def subscribe_to_order_updates(self, handler: FillEventHandler) -> None:
        """Subscribe to real-time order update events via WebSocket.

        :param handler: Async callable receiving an order update dict.
        """
        if not self._cli.address:
            raise client.Error("Private key required to subscribe to order updates")

        channel = websockets._order_updates_channel(self._cli.address)
        event_source = self._ws.get_channel_event_source(channel)
        if event_source is None:
            event_source = websockets.RawEventSource(producer=self._ws)
            self._ws.set_channel_event_source(channel, event_source)
        self._dispatcher.subscribe(event_source, cast(dispatcher.EventHandler, handler))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_order_result(result: dict, coin: str, is_buy: Optional[bool] = None) -> OrderInfo:
        statuses = result.get("response", {}).get("data", {}).get("statuses", [{}])
        s = statuses[0] if statuses else {}
        filled = s.get("filled", {})
        if is_buy is None:
            side = filled.get("side") or s.get("side")
            if side == "B":
                is_buy = True
            elif side == "A":
                is_buy = False
            else:
                is_buy = False
        return OrderInfo(
            oid=filled.get("oid", 0),
            coin=coin,
            is_buy=is_buy,
            size=Decimal(str(filled.get("totalSz", "0"))),
            limit_price=None,
            filled=Decimal(str(filled.get("totalSz", "0"))),
            status="filled" if filled else s.get("error", "unknown"),
        )

    @staticmethod
    def _parse_fill(raw: dict) -> FillEvent:
        when = helpers.timestamp_to_datetime(int(raw["time"]))
        return FillEvent(
            coin=raw["coin"],
            oid=int(raw.get("oid", 0)),
            is_buy=raw.get("side", "") == "B",
            size=Decimal(str(raw["sz"])),
            price=Decimal(str(raw["px"])),
            fee=Decimal(str(raw.get("fee", "0"))),
            realized_pnl=Decimal(str(raw.get("closedPnl", "0"))),
            when=when,
            is_maker=raw.get("liquidation", "") == "" and raw.get("crossed", True) is False,
        )

    @staticmethod
    def _parse_funding(coin: str, raw: dict) -> FundingPayment:
        when = helpers.timestamp_to_datetime(int(raw["time"]))
        return FundingPayment(
            coin=coin,
            rate=Decimal(str(raw["fundingRate"])),
            payment=Decimal(str(raw.get("payment", "0"))),
            when=when,
        )
