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
import datetime

import pytest

import basana as bs
from basana.external.hyperliquid.exchange import Exchange, Error
from basana.external.hyperliquid.perps import Account, FillEvent, FundingPayment, Position


# ---------------------------------------------------------------------------
# Position dataclass tests
# ---------------------------------------------------------------------------


class TestPosition:
    def test_is_long(self):
        pos = Position(
            coin="ETH", size=Decimal("1.5"), entry_price=Decimal("2000"),
            unrealized_pnl=Decimal("100"), liquidation_price=Decimal("1500"),
            leverage=Decimal("10"), margin_used=Decimal("200"),
        )
        assert pos.is_long is True
        assert pos.is_short is False

    def test_is_short(self):
        pos = Position(
            coin="ETH", size=Decimal("-1.5"), entry_price=Decimal("2000"),
            unrealized_pnl=Decimal("-50"), liquidation_price=Decimal("2500"),
            leverage=Decimal("10"), margin_used=Decimal("200"),
        )
        assert pos.is_short is True
        assert pos.is_long is False

    def test_notional_value(self):
        pos = Position(
            coin="ETH", size=Decimal("2"), entry_price=Decimal("2000"),
            unrealized_pnl=Decimal("0"), liquidation_price=None,
            leverage=Decimal("1"), margin_used=Decimal("4000"),
        )
        assert pos.notional_value == Decimal("4000")

    def test_notional_value_short(self):
        pos = Position(
            coin="ETH", size=Decimal("-3"), entry_price=Decimal("2000"),
            unrealized_pnl=Decimal("0"), liquidation_price=None,
            leverage=Decimal("1"), margin_used=Decimal("6000"),
        )
        assert pos.notional_value == Decimal("6000")

    def test_return_on_equity(self):
        pos = Position(
            coin="ETH", size=Decimal("1"), entry_price=Decimal("2000"),
            unrealized_pnl=Decimal("100"), liquidation_price=None,
            leverage=Decimal("10"), margin_used=Decimal("200"),
        )
        assert pos.return_on_equity == Decimal("0.5")

    def test_return_on_equity_zero_margin(self):
        pos = Position(
            coin="ETH", size=Decimal("1"), entry_price=Decimal("2000"),
            unrealized_pnl=Decimal("100"), liquidation_price=None,
            leverage=Decimal("10"), margin_used=Decimal("0"),
        )
        assert pos.return_on_equity is None

    def test_liquidation_distance_pct_with_mark_price(self):
        pos = Position(
            coin="ETH", size=Decimal("1"), entry_price=Decimal("2000"),
            unrealized_pnl=Decimal("0"), liquidation_price=Decimal("1800"),
            leverage=Decimal("10"), margin_used=Decimal("200"),
            mark_price=Decimal("2000"),
        )
        assert pos.liquidation_distance_pct == Decimal("10")

    def test_liquidation_distance_pct_without_mark_uses_entry(self):
        pos = Position(
            coin="ETH", size=Decimal("1"), entry_price=Decimal("2000"),
            unrealized_pnl=Decimal("0"), liquidation_price=Decimal("1800"),
            leverage=Decimal("10"), margin_used=Decimal("200"),
        )
        assert pos.liquidation_distance_pct == Decimal("10")

    def test_liquidation_distance_pct_none_when_no_liq_price(self):
        pos = Position(
            coin="ETH", size=Decimal("1"), entry_price=Decimal("2000"),
            unrealized_pnl=Decimal("0"), liquidation_price=None,
            leverage=Decimal("10"), margin_used=Decimal("200"),
        )
        assert pos.liquidation_distance_pct is None

    def test_liquidation_distance_pct_zero_entry_price(self):
        pos = Position(
            coin="ETH", size=Decimal("1"), entry_price=Decimal("0"),
            unrealized_pnl=Decimal("0"), liquidation_price=Decimal("100"),
            leverage=Decimal("10"), margin_used=Decimal("0"),
        )
        assert pos.liquidation_distance_pct is None

    def test_mark_price_default_none(self):
        pos = Position(
            coin="ETH", size=Decimal("1"), entry_price=Decimal("2000"),
            unrealized_pnl=Decimal("0"), liquidation_price=None,
            leverage=Decimal("1"), margin_used=Decimal("2000"),
        )
        assert pos.mark_price is None
        assert pos.cumulative_funding is None

    def test_cumulative_funding(self):
        pos = Position(
            coin="ETH", size=Decimal("1"), entry_price=Decimal("2000"),
            unrealized_pnl=Decimal("0"), liquidation_price=None,
            leverage=Decimal("1"), margin_used=Decimal("2000"),
            cumulative_funding=Decimal("-5.50"),
        )
        assert pos.cumulative_funding == Decimal("-5.50")


# ---------------------------------------------------------------------------
# FillEvent dataclass tests
# ---------------------------------------------------------------------------


class TestFillEvent:
    def test_fill_event_fields(self):
        when = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
        fill = FillEvent(
            coin="ETH", oid=123, is_buy=True, size=Decimal("0.5"),
            price=Decimal("2000"), fee=Decimal("1.0"),
            realized_pnl=Decimal("0"), when=when,
        )
        assert fill.coin == "ETH"
        assert fill.is_buy is True
        assert fill.is_maker is False

    def test_fill_event_maker(self):
        when = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
        fill = FillEvent(
            coin="ETH", oid=123, is_buy=True, size=Decimal("0.5"),
            price=Decimal("2000"), fee=Decimal("0.5"),
            realized_pnl=Decimal("50"), when=when, is_maker=True,
        )
        assert fill.is_maker is True
        assert fill.realized_pnl == Decimal("50")


# ---------------------------------------------------------------------------
# FundingPayment dataclass tests
# ---------------------------------------------------------------------------


class TestFundingPayment:
    def test_funding_payment_fields(self):
        when = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
        fp = FundingPayment(
            coin="ETH", rate=Decimal("0.0001"),
            payment=Decimal("-0.50"), when=when,
        )
        assert fp.coin == "ETH"
        assert fp.rate == Decimal("0.0001")
        assert fp.payment == Decimal("-0.50")


# ---------------------------------------------------------------------------
# Account.get_positions with enriched data
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_info():
    with patch("basana.external.hyperliquid.client.rest.Info") as MockInfo:
        yield MockInfo.return_value


@pytest.fixture()
def mock_exchange_sdk():
    with patch("basana.external.hyperliquid.client.rest.HLExchange") as MockEx:
        yield MockEx.return_value


@pytest.fixture()
def mock_account():
    with patch("basana.external.hyperliquid.client.rest.eth_account") as mock_eth:
        mock_wallet = MagicMock()
        mock_wallet.address = "0xDEADBEEF"
        mock_eth.Account.from_key.return_value = mock_wallet
        yield mock_eth


class TestAccountPositions:
    def test_positions_include_mark_price(self, mock_info, mock_account, mock_exchange_sdk):
        mock_info.user_state.return_value = {
            "marginSummary": {"accountValue": "10000"},
            "assetPositions": [{
                "position": {
                    "coin": "ETH", "szi": "1.0", "entryPx": "2000",
                    "unrealizedPnl": "100", "liquidationPx": "1800",
                    "leverage": {"value": 10}, "marginUsed": "200",
                    "cumFunding": {"sinceOpen": "-5.5"},
                }
            }],
        }
        mock_info.all_mids.return_value = {"ETH": "2100.0"}

        from basana.external.hyperliquid.client.rest import APIClient
        cli = APIClient(private_key="0xdeadbeef")
        ws = MagicMock()
        d = bs.realtime_dispatcher()
        account = Account(cli, ws, d)

        positions = asyncio.run(account.get_positions())
        assert len(positions) == 1
        pos = positions[0]
        assert pos.mark_price == Decimal("2100.0")
        assert pos.cumulative_funding == Decimal("-5.5")

    def test_positions_without_mids_fallback(self, mock_info, mock_account, mock_exchange_sdk):
        mock_info.user_state.return_value = {
            "marginSummary": {"accountValue": "10000"},
            "assetPositions": [{
                "position": {
                    "coin": "ETH", "szi": "1.0", "entryPx": "2000",
                    "unrealizedPnl": "0", "leverage": {"value": 1}, "marginUsed": "2000",
                }
            }],
        }
        mock_info.all_mids.side_effect = Exception("API error")

        from basana.external.hyperliquid.client.rest import APIClient
        cli = APIClient(private_key="0xdeadbeef")
        ws = MagicMock()
        d = bs.realtime_dispatcher()
        account = Account(cli, ws, d)

        positions = asyncio.run(account.get_positions())
        assert len(positions) == 1
        assert positions[0].mark_price is None


# ---------------------------------------------------------------------------
# Account.get_funding_history
# ---------------------------------------------------------------------------


class TestAccountFunding:
    def test_get_funding_history(self, mock_info, mock_account, mock_exchange_sdk):
        mock_info.funding_history.return_value = [
            {"time": 1700000000000, "fundingRate": "0.0001", "payment": "-0.50"},
            {"time": 1700003600000, "fundingRate": "0.0002", "payment": "1.20"},
        ]

        from basana.external.hyperliquid.client.rest import APIClient
        cli = APIClient(private_key="0xdeadbeef")
        ws = MagicMock()
        d = bs.realtime_dispatcher()
        account = Account(cli, ws, d)

        start = datetime.datetime(2023, 11, 14, tzinfo=datetime.timezone.utc)
        payments = asyncio.run(account.get_funding_history("ETH", start))
        assert len(payments) == 2
        assert payments[0].rate == Decimal("0.0001")
        assert payments[0].payment == Decimal("-0.50")
        assert payments[1].rate == Decimal("0.0002")
        assert payments[0].when.tzinfo is not None


# ---------------------------------------------------------------------------
# Account.get_fills
# ---------------------------------------------------------------------------


class TestAccountFills:
    def test_get_fills(self, mock_info, mock_account, mock_exchange_sdk):
        mock_info.user_fills_by_time.return_value = [
            {
                "coin": "ETH", "oid": 42, "side": "B", "sz": "1.0",
                "px": "2000", "fee": "2.0", "closedPnl": "0", "time": 1700000000000,
                "crossed": True,
            },
        ]

        from basana.external.hyperliquid.client.rest import APIClient
        cli = APIClient(private_key="0xdeadbeef")
        ws = MagicMock()
        d = bs.realtime_dispatcher()
        account = Account(cli, ws, d)

        start = datetime.datetime(2023, 11, 14, tzinfo=datetime.timezone.utc)
        fills = asyncio.run(account.get_fills(start))
        assert len(fills) == 1
        assert fills[0].coin == "ETH"
        assert fills[0].is_buy is True
        assert fills[0].size == Decimal("1.0")
        assert fills[0].fee == Decimal("2.0")
        assert fills[0].when.tzinfo is not None


# ---------------------------------------------------------------------------
# Account.get_margin_summary
# ---------------------------------------------------------------------------


class TestAccountMarginSummary:
    def test_get_margin_summary(self, mock_info, mock_account, mock_exchange_sdk):
        mock_info.user_state.return_value = {
            "marginSummary": {
                "accountValue": "10000", "totalMarginUsed": "2000",
                "totalNtlPos": "20000",
            },
            "assetPositions": [],
        }

        from basana.external.hyperliquid.client.rest import APIClient
        cli = APIClient(private_key="0xdeadbeef")
        ws = MagicMock()
        d = bs.realtime_dispatcher()
        account = Account(cli, ws, d)

        summary = asyncio.run(account.get_margin_summary())
        assert summary["accountValue"] == "10000"
        assert summary["totalMarginUsed"] == "2000"


# ---------------------------------------------------------------------------
# Account.subscribe_to_order_updates
# ---------------------------------------------------------------------------


class TestOrderUpdates:
    def test_subscribe_to_order_updates(self, mock_info, mock_account, mock_exchange_sdk):
        from basana.external.hyperliquid.client.rest import APIClient
        cli = APIClient(private_key="0xdeadbeef")
        ws = MagicMock()
        ws.get_channel_event_source.return_value = None
        d = bs.realtime_dispatcher()
        d.subscribe = MagicMock()
        account = Account(cli, ws, d)

        handler = AsyncMock()
        account.subscribe_to_order_updates(handler)

        ws.set_channel_event_source.assert_called_once()
        channel = ws.set_channel_event_source.call_args[0][0]
        assert "orderUpdates" in channel
        d.subscribe.assert_called_once()

    def test_subscribe_to_order_updates_requires_auth(self, mock_info):
        from basana.external.hyperliquid.client.rest import APIClient
        cli = APIClient()
        ws = MagicMock()
        d = bs.realtime_dispatcher()
        account = Account(cli, ws, d)

        with pytest.raises(Exception, match="Private key required"):
            account.subscribe_to_order_updates(AsyncMock())


# ---------------------------------------------------------------------------
# Exchange.get_mark_price
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_api_client():
    with patch("basana.external.hyperliquid.exchange.client.APIClient") as MockClient:
        instance = MockClient.return_value
        instance.get_all_mids = AsyncMock(return_value={"ETH": "2100.0", "BTC": "70000.0"})
        instance.get_l2_snapshot = AsyncMock(return_value={
            "levels": [[{"px": "2099.5"}], [{"px": "2100.5"}]],
        })
        instance.get_meta = AsyncMock(return_value={
            "universe": [
                {"name": "BTC", "szDecimals": 5, "maxLeverage": 50},
                {"name": "ETH", "szDecimals": 4, "maxLeverage": 25},
            ]
        })
        instance.get_funding_history = AsyncMock(return_value=[
            {"time": 1700000000000, "fundingRate": "0.00015"},
        ])
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


class TestExchangeMarkPrice:
    def test_get_mark_price(self, exchange):
        price = asyncio.run(exchange.get_mark_price("ETH"))
        assert price == Decimal("2100.0")

    def test_get_mark_price_unknown_coin_raises(self, exchange):
        with pytest.raises(Error, match="Unknown coin"):
            asyncio.run(exchange.get_mark_price("NOTACOIN"))


class TestExchangeFundingRate:
    def test_get_funding_rate(self, exchange):
        rate = asyncio.run(exchange.get_funding_rate("ETH"))
        assert rate == Decimal("0.00015")

    def test_get_funding_rate_empty_history(self, exchange, mock_api_client):
        mock_api_client.get_funding_history = AsyncMock(return_value=[])
        rate = asyncio.run(exchange.get_funding_rate("ETH"))
        assert rate is None
