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

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

import basana as bs
from basana.external.hyperliquid.exchange import Exchange, Error, AssetInfo


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_api_client():
    with patch("basana.external.hyperliquid.exchange.client.APIClient") as MockClient:
        instance = MockClient.return_value
        instance.get_all_mids = AsyncMock(return_value={"ETH": "2100.0", "BTC": "70000.0", "SOL": "150.0"})
        instance.get_l2_snapshot = AsyncMock(
            return_value={
                "coin": "ETH",
                "levels": [
                    [{"px": "2099.5", "sz": "2.0", "n": 1}],
                    [{"px": "2100.5", "sz": "1.5", "n": 1}],
                ],
            }
        )
        instance.get_meta = AsyncMock(
            return_value={
                "universe": [
                    {"name": "BTC", "szDecimals": 5, "maxLeverage": 50},
                    {"name": "ETH", "szDecimals": 4, "maxLeverage": 25},
                    {"name": "SOL", "szDecimals": 2, "maxLeverage": 20},
                ]
            }
        )
        yield instance


@pytest.fixture()
def mock_ws_client():
    with patch("basana.external.hyperliquid.exchange.websockets.WebSocketClient") as MockWS:
        instance = MockWS.return_value
        instance.set_channel_event_source = MagicMock()
        yield instance


@pytest.fixture()
def exchange(mock_api_client, mock_ws_client):
    d = bs.realtime_dispatcher()
    return Exchange(dispatcher=d)


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------


class TestMarketData:
    def test_get_mid_price(self, exchange):
        price = asyncio.run(exchange.get_mid_price("ETH"))
        assert price == Decimal("2100.0")
        assert isinstance(price, Decimal)

    def test_get_mid_price_unknown_coin_raises(self, exchange):
        with pytest.raises(Error, match="Unknown coin"):
            asyncio.run(exchange.get_mid_price("NOTACOIN"))

    def test_get_bid_ask(self, exchange):
        bid, ask = asyncio.run(exchange.get_bid_ask("ETH"))
        assert bid == Decimal("2099.5")
        assert ask == Decimal("2100.5")
        assert ask > bid

    def test_get_pair_info(self, exchange):
        info = asyncio.run(exchange.get_pair_info("ETH"))
        assert isinstance(info, AssetInfo)
        assert info.sz_decimals == 4
        assert info.max_leverage == 25

    def test_get_pair_info_btc(self, exchange):
        info = asyncio.run(exchange.get_pair_info("BTC"))
        assert info.sz_decimals == 5
        assert info.max_leverage == 50

    def test_get_pair_info_cached(self, exchange, mock_api_client):
        asyncio.run(exchange.get_pair_info("ETH"))
        asyncio.run(exchange.get_pair_info("ETH"))
        mock_api_client.get_meta.assert_called_once()

    def test_get_pair_info_unknown_coin_raises(self, exchange, mock_api_client):
        with pytest.raises(Error, match="Unknown coin"):
            asyncio.run(exchange.get_pair_info("NOTACOIN"))
        assert mock_api_client.get_meta.await_count == 1

    def test_list_coins(self, exchange):
        coins = asyncio.run(exchange.list_coins())
        assert "BTC" in coins and "ETH" in coins and "SOL" in coins
        assert len(coins) == 3


# ---------------------------------------------------------------------------
# WebSocket subscriptions
# ---------------------------------------------------------------------------


class TestSubscriptions:
    def test_subscribe_to_bar_events(self, exchange, mock_ws_client):
        handler = AsyncMock()
        exchange.subscribe_to_bar_events("ETH", "1h", handler)
        mock_ws_client.set_channel_event_source.assert_called_once()
        args = mock_ws_client.set_channel_event_source.call_args[0]
        assert args[0] == "candle:ETH:1h"

    def test_subscribe_to_trade_events(self, exchange, mock_ws_client):
        handler = AsyncMock()
        exchange.subscribe_to_trade_events("ETH", handler)
        mock_ws_client.set_channel_event_source.assert_called_once()
        args = mock_ws_client.set_channel_event_source.call_args[0]
        assert args[0] == "trades:ETH"

    def test_subscribe_to_order_book_events(self, exchange, mock_ws_client):
        handler = AsyncMock()
        exchange.subscribe_to_order_book_events("ETH", handler)
        mock_ws_client.set_channel_event_source.assert_called_once()
        args = mock_ws_client.set_channel_event_source.call_args[0]
        assert args[0] == "l2Book:ETH"


# ---------------------------------------------------------------------------
# Bar event construction
# ---------------------------------------------------------------------------


class TestBarEventSource:
    def test_candle_to_bar_event(self):
        from basana.external.hyperliquid.exchange import BarEventSource
        from basana.core.pair import Pair

        pair = Pair("ETH", "USD")
        producer = MagicMock()
        producer.initialize = MagicMock()
        source = BarEventSource(pair=pair, producer=producer)

        events = []

        async def run():
            await source.push_from_message(
                {
                    "t": 1709500000000,
                    "T": 1709503600000,
                    "o": "2100.0",
                    "h": "2150.0",
                    "l": "2090.0",
                    "c": "2130.0",
                    "v": "500.5",
                    "coin": "ETH",
                }
            )
            while True:
                event = source.pop()
                if event is None:
                    break
                events.append(event)

        asyncio.run(run())
        assert len(events) == 1
        bar_event = events[0]
        assert bar_event.bar.close == Decimal("2130.0")
        assert bar_event.bar.pair == pair
        assert bar_event.when.tzinfo is not None

    def test_malformed_candle_does_not_raise(self):
        from basana.external.hyperliquid.exchange import BarEventSource
        from basana.core.pair import Pair

        pair = Pair("ETH", "USD")
        producer = MagicMock()
        source = BarEventSource(pair=pair, producer=producer)
        # Should log a warning but not raise
        asyncio.run(source.push_from_message({"invalid": "data"}))


class TestWebSocketRouting:
    def test_candle_interval_is_part_of_route_key(self):
        from basana.external.hyperliquid import websockets

        assert (
            websockets.WebSocketClient._message_to_registered_channel("candle", {"coin": "ETH", "interval": "1h"})
            == "candle:ETH:1h"
        )
        assert (
            websockets.WebSocketClient._message_to_registered_channel("candle", {"coin": "ETH", "interval": "5m"})
            == "candle:ETH:5m"
        )


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestTestnetConfig:
    def test_testnet_exchange(self, mock_api_client, mock_ws_client):
        d = bs.realtime_dispatcher()
        exchange = Exchange(dispatcher=d, testnet=True)
        assert exchange is not None

    def test_testnet_with_overrides(self, mock_api_client, mock_ws_client):
        d = bs.realtime_dispatcher()
        exchange = Exchange(
            dispatcher=d,
            testnet=True,
            config_overrides={"api": {"http": {"timeout": 30}}},
        )
        assert exchange is not None


class TestHelpers:
    def test_pair_to_coin(self):
        from basana.external.hyperliquid.helpers import pair_to_coin
        from basana.core.pair import Pair

        assert pair_to_coin(Pair("eth", "usd")) == "ETH"
        assert pair_to_coin(Pair("BTC", "USD")) == "BTC"


class TestLifecycle:
    def test_perps_account_accessible(self, exchange):
        from basana.external.hyperliquid.perps import Account

        assert isinstance(exchange.perps_account, Account)


class TestPerpsAccount:
    def test_subscribe_to_fill_events_registers_handler(self, mock_api_client, mock_ws_client):
        d = bs.realtime_dispatcher()
        d.subscribe = MagicMock()
        mock_api_client.address = "0xDEADBEEF"
        mock_ws_client.get_channel_event_source.return_value = None
        exchange = Exchange(dispatcher=d, private_key="0xdeadbeef")
        handler = AsyncMock()

        exchange.perps_account.subscribe_to_fill_events(handler)

        mock_ws_client.set_channel_event_source.assert_called_once()
        d.subscribe.assert_called_once()
        subscribe_args = d.subscribe.call_args[0]
        assert subscribe_args[1] is handler

    def test_subscribe_to_fill_events_no_key_raises(self, mock_api_client, mock_ws_client):
        mock_api_client.address = None
        d = bs.realtime_dispatcher()
        exchange = Exchange(dispatcher=d)
        with pytest.raises(Exception, match="Private key required"):
            exchange.perps_account.subscribe_to_fill_events(AsyncMock())

    def test_get_positions(self, mock_api_client, mock_ws_client):
        mock_api_client.get_user_state = AsyncMock(return_value={
            "marginSummary": {"accountValue": "10000"},
            "assetPositions": [{
                "position": {
                    "coin": "ETH", "szi": "1.0", "entryPx": "2000",
                    "unrealizedPnl": "100", "liquidationPx": "1800",
                    "leverage": {"value": 10}, "marginUsed": "200",
                }
            }, {
                "position": {"coin": "BTC", "szi": "0"}  # should be skipped
            }],
        })
        d = bs.realtime_dispatcher()
        exchange = Exchange(dispatcher=d, private_key="0xdeadbeef")
        positions = asyncio.run(exchange.perps_account.get_positions())
        assert len(positions) == 1
        assert positions[0].coin == "ETH"
        assert positions[0].size == Decimal("1.0")
        assert positions[0].leverage == Decimal("10")

    def test_get_balance(self, mock_api_client, mock_ws_client):
        mock_api_client.get_user_state = AsyncMock(return_value={
            "marginSummary": {"accountValue": "5000.0"},
            "assetPositions": [],
        })
        d = bs.realtime_dispatcher()
        exchange = Exchange(dispatcher=d, private_key="0xdeadbeef")
        balance = asyncio.run(exchange.perps_account.get_balance())
        assert balance == Decimal("5000.0")

    def test_get_open_orders(self, mock_api_client, mock_ws_client):
        mock_api_client.get_open_orders = AsyncMock(return_value=[
            {"oid": 1, "coin": "ETH", "side": "B", "sz": "0.5", "limitPx": "2000", "orderType": "Limit"},
        ])
        d = bs.realtime_dispatcher()
        exchange = Exchange(dispatcher=d, private_key="0xdeadbeef")
        orders = asyncio.run(exchange.perps_account.get_open_orders())
        assert len(orders) == 1
        assert orders[0].oid == 1
        assert orders[0].is_buy is True

    def test_market_open(self, mock_api_client, mock_ws_client):
        mock_api_client.market_open = AsyncMock(return_value={
            "response": {"data": {"statuses": [{"filled": {"oid": 7, "totalSz": "0.5", "side": "B"}}]}}
        })
        d = bs.realtime_dispatcher()
        exchange = Exchange(dispatcher=d, private_key="0xdeadbeef")
        from basana.core.enums import OrderOperation
        order = asyncio.run(exchange.perps_account.market_open("ETH", OrderOperation.BUY, Decimal("0.5")))
        assert order.is_buy is True
        assert order.filled == Decimal("0.5")

    def test_market_close(self, mock_api_client, mock_ws_client):
        mock_api_client.market_close = AsyncMock(return_value={
            "response": {"data": {"statuses": [{"filled": {"oid": 8, "totalSz": "0.5", "side": "A"}}]}}
        })
        d = bs.realtime_dispatcher()
        exchange = Exchange(dispatcher=d, private_key="0xdeadbeef")
        order = asyncio.run(exchange.perps_account.market_close("ETH"))
        assert order.filled == Decimal("0.5")

    def test_limit_order(self, mock_api_client, mock_ws_client):
        mock_api_client.limit_order = AsyncMock(return_value={
            "response": {"data": {"statuses": [{"filled": {"oid": 9, "totalSz": "1.0", "side": "B"}}]}}
        })
        d = bs.realtime_dispatcher()
        exchange = Exchange(dispatcher=d, private_key="0xdeadbeef")
        from basana.core.enums import OrderOperation
        order = asyncio.run(exchange.perps_account.limit_order(
            "ETH", OrderOperation.BUY, Decimal("1.0"), Decimal("2000"), reduce_only=True
        ))
        assert order.oid == 9

    def test_cancel_order(self, mock_api_client, mock_ws_client):
        mock_api_client.cancel_order = AsyncMock(return_value={"status": "ok"})
        d = bs.realtime_dispatcher()
        exchange = Exchange(dispatcher=d, private_key="0xdeadbeef")
        asyncio.run(exchange.perps_account.cancel_order("ETH", 123))
        mock_api_client.cancel_order.assert_called_once_with("ETH", 123)

    def test_set_leverage(self, mock_api_client, mock_ws_client):
        mock_api_client.set_leverage = AsyncMock(return_value={"status": "ok"})
        d = bs.realtime_dispatcher()
        exchange = Exchange(dispatcher=d, private_key="0xdeadbeef")
        asyncio.run(exchange.perps_account.set_leverage("ETH", 10, is_cross=True))
        mock_api_client.set_leverage.assert_called_once_with("ETH", 10, True)

    def test_parse_order_result_infers_sell_side(self):
        from basana.external.hyperliquid.perps import Account
        order = Account._parse_order_result(
            {"response": {"data": {"statuses": [{"filled": {"oid": 1, "totalSz": "1", "side": "A"}}]}}},
            "ETH",
        )
        assert order.is_buy is False

    def test_parse_order_result_infers_buy_side(self):
        from basana.external.hyperliquid.perps import Account
        order = Account._parse_order_result(
            {"response": {"data": {"statuses": [{"filled": {"oid": 1, "totalSz": "1", "side": "B"}}]}}},
            "ETH",
        )
        assert order.is_buy is True

    def test_parse_order_result_unknown_side(self):
        from basana.external.hyperliquid.perps import Account
        order = Account._parse_order_result(
            {"response": {"data": {"statuses": [{"filled": {"oid": 1, "totalSz": "1"}}]}}},
            "ETH",
        )
        assert order.is_buy is False
