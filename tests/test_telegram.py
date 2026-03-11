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
import asyncio
import datetime

from dateutil import tz

import basana as bs
from basana.core.risk import DeploymentMode, PortfolioTracker, RiskManager
from basana.external.telegram.auth import UserAuthenticator, require_auth
from basana.external.telegram.config import TelegramConfig, Verbosity
from basana.external.telegram.formatters import (
    format_deployment_mode,
    format_fill_notification,
    format_portfolio_summary,
    format_positions_list,
    format_risk_status,
    format_signal_notification,
)
from basana.external.telegram.rate_limit import UserRateLimiter

utc = tz.UTC
btc_pair = bs.Pair("BTC", "USD")
eth_pair = bs.Pair("ETH", "USD")


def _dt(day=1, hour=12):
    return datetime.datetime(2026, 1, day, hour, 0, 0, tzinfo=utc)


# --- Config tests ---


def test_config_defaults():
    config = TelegramConfig(
        bot_token="0000000000:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        authorized_user_ids=[12345],
    )
    assert config.verbosity == Verbosity.NORMAL
    assert config.rate_limit_messages_per_minute == 30
    assert config.notify_on_fill is True
    assert config.notify_on_signal is True
    assert config.notify_on_risk_breach is True


def test_config_custom_values():
    config = TelegramConfig(
        bot_token="0000000000:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        authorized_user_ids=[1, 2, 3],
        verbosity=Verbosity.QUIET,
        rate_limit_messages_per_minute=10,
        notify_on_fill=False,
    )
    assert config.verbosity == Verbosity.QUIET
    assert config.rate_limit_messages_per_minute == 10
    assert config.notify_on_fill is False
    assert len(config.authorized_user_ids) == 3


def test_verbosity_enum_values():
    assert Verbosity.QUIET.value == "quiet"
    assert Verbosity.NORMAL.value == "normal"
    assert Verbosity.VERBOSE.value == "verbose"


# --- Auth tests ---


def test_auth_authorized_user():
    auth = UserAuthenticator({111, 222})
    assert auth.is_authorized(111) is True
    assert auth.is_authorized(222) is True


def test_auth_unauthorized_user():
    auth = UserAuthenticator({111})
    assert auth.is_authorized(999) is False


def test_auth_empty_allowlist():
    auth = UserAuthenticator(set())
    assert auth.is_authorized(1) is False


def test_require_auth_blocks_unauthorized():
    auth = UserAuthenticator({111})

    @require_auth(auth)
    async def handler(update, context):
        return "ok"

    class FakeUser:
        id = 999

    class FakeMessage:
        def __init__(self):
            self.replied = None

        async def reply_text(self, text):
            self.replied = text

    class FakeUpdate:
        effective_user = FakeUser()
        effective_message = FakeMessage()

    async def impl():
        update = FakeUpdate()
        result = await handler(update, None)
        assert result is None
        assert update.effective_message.replied == "Unauthorized."

    asyncio.run(impl())


def test_require_auth_allows_authorized():
    auth = UserAuthenticator({111})

    @require_auth(auth)
    async def handler(update, context):
        return "ok"

    class FakeUser:
        id = 111

    class FakeUpdate:
        effective_user = FakeUser()
        effective_message = None

    async def impl():
        result = await handler(FakeUpdate(), None)
        assert result == "ok"

    asyncio.run(impl())


def test_require_auth_no_user():
    auth = UserAuthenticator({111})

    @require_auth(auth)
    async def handler(update, context):
        return "ok"

    class FakeMessage:
        def __init__(self):
            self.replied = None

        async def reply_text(self, text):
            self.replied = text

    class FakeUpdate:
        effective_user = None
        effective_message = FakeMessage()

    async def impl():
        update = FakeUpdate()
        result = await handler(update, None)
        assert result is None
        assert update.effective_message.replied == "Unauthorized."

    asyncio.run(impl())


# --- Rate limiter tests ---


def test_rate_limiter_under_limit():
    limiter = UserRateLimiter(messages_per_minute=30)
    # First message should pass (initial tokens = 30).
    wait = limiter.check(user_id=1)
    assert wait == 0.0


def test_rate_limiter_over_limit():
    limiter = UserRateLimiter(messages_per_minute=2)
    # Consume all tokens.
    limiter.check(user_id=1)
    limiter.check(user_id=1)
    # Third should require waiting.
    wait = limiter.check(user_id=1)
    assert wait > 0.0


def test_rate_limiter_wait():
    limiter = UserRateLimiter(messages_per_minute=30)

    async def impl():
        await limiter.wait(user_id=1)

    asyncio.run(impl())


def test_rate_limiter_per_user_isolation():
    limiter = UserRateLimiter(messages_per_minute=1)
    # User 1 consumes their token.
    limiter.check(user_id=1)
    # User 2 should still have their own token.
    wait = limiter.check(user_id=2)
    assert wait == 0.0


# --- Formatter tests ---


def test_format_portfolio_summary():
    tracker = PortfolioTracker(initial_cash=Decimal("10000"))
    tracker.record_fill(btc_pair, Decimal("1"), Decimal("50000"), _dt())
    tracker.update_price(btc_pair, Decimal("51000"))
    snapshot = tracker.snapshot(_dt())

    text = format_portfolio_summary(snapshot)
    assert "Portfolio Summary" in text
    assert "Equity" in text
    assert "Gross Exposure" in text
    assert "Unrealized P&L" in text


def test_format_positions_list_with_positions():
    tracker = PortfolioTracker(initial_cash=Decimal("10000"))
    tracker.record_fill(btc_pair, Decimal("1"), Decimal("50000"), _dt())
    tracker.update_price(btc_pair, Decimal("51000"))
    snapshot = tracker.snapshot(_dt())

    text = format_positions_list(snapshot)
    assert "BTC/USD" in text
    assert "LONG" in text
    assert "Entry" in text


def test_format_positions_list_empty():
    tracker = PortfolioTracker(initial_cash=Decimal("10000"))
    snapshot = tracker.snapshot(_dt())

    text = format_positions_list(snapshot)
    assert text == "No open positions."


def test_format_positions_list_short():
    tracker = PortfolioTracker(initial_cash=Decimal("10000"))
    tracker.record_fill(btc_pair, Decimal("-1"), Decimal("50000"), _dt())
    tracker.update_price(btc_pair, Decimal("49000"))
    snapshot = tracker.snapshot(_dt())

    text = format_positions_list(snapshot)
    assert "SHORT" in text


def test_format_fill_notification():
    text = format_fill_notification(
        pair=btc_pair,
        signed_qty=Decimal("0.5"),
        fill_price=Decimal("50000"),
        when=_dt(),
    )
    assert "Fill: BTC/USD" in text
    assert "BUY" in text
    assert "0.5" in text
    assert "50000" in text


def test_format_fill_notification_sell():
    text = format_fill_notification(
        pair=btc_pair,
        signed_qty=Decimal("-0.5"),
        fill_price=Decimal("50000"),
        when=_dt(),
    )
    assert "SELL" in text


def test_format_signal_notification():
    text = format_signal_notification(
        pair=btc_pair,
        position="long",
        when=_dt(),
    )
    assert "Signal: BTC/USD" in text
    assert "long" in text


def test_format_risk_status_inactive():
    text = format_risk_status(
        mode=DeploymentMode.LIVE,
        kill_switch_active=False,
        kill_switch_reason=None,
    )
    assert "LIVE" in text
    assert "inactive" in text


def test_format_risk_status_active():
    text = format_risk_status(
        mode=DeploymentMode.MONITOR,
        kill_switch_active=True,
        kill_switch_reason="Testing",
    )
    assert "MONITOR" in text
    assert "ACTIVE" in text
    assert "Testing" in text


def test_format_deployment_mode():
    text = format_deployment_mode(DeploymentMode.PAPER)
    assert "PAPER" in text


# --- RiskManager.set_mode test ---


def test_set_mode():
    dispatcher = bs.backtesting_dispatcher()
    portfolio = PortfolioTracker(initial_cash=Decimal("10000"))
    mgr = RiskManager(dispatcher, portfolio, mode=DeploymentMode.LIVE)

    assert mgr.mode == DeploymentMode.LIVE

    mgr.set_mode(DeploymentMode.PAPER)
    assert mgr.mode == DeploymentMode.PAPER

    mgr.set_mode(DeploymentMode.MONITOR)
    assert mgr.mode == DeploymentMode.MONITOR
