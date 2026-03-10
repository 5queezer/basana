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

from dateutil import tz

import basana as bs
from basana.core.strategy import (
    BarrierConfig,
    BarrierResult,
    BarrierStatus,
    ExitReason,
    TripleBarrier,
)

utc = tz.UTC
btc_pair = bs.Pair("BTC", "USD")


def _dt(day=1, hour=12, minute=0):
    return datetime.datetime(2026, 1, day, hour, minute, 0, tzinfo=utc)


# --- BarrierConfig tests ---


def test_barrier_config_defaults():
    config = BarrierConfig()
    assert config.stop_loss_pct is None
    assert config.take_profit_pct is None
    assert config.time_limit is None
    assert config.trailing_stop_pct is None
    assert config.break_even_pct is None
    assert config.partial_take_profit_pct is None
    assert config.partial_take_profit_fraction == Decimal("0.5")


def test_barrier_config_frozen():
    config = BarrierConfig(stop_loss_pct=Decimal("2"))
    try:
        config.stop_loss_pct = Decimal("3")  # type: ignore[misc]
        assert False, "Should have raised"
    except AttributeError:
        pass


def test_barrier_result_frozen():
    result = BarrierResult(hit=True, reason=ExitReason.STOP_LOSS)
    try:
        result.hit = False  # type: ignore[misc]
        assert False, "Should have raised"
    except AttributeError:
        pass


def test_barrier_result_defaults():
    result = BarrierResult(hit=False)
    assert result.reason is None
    assert result.exit_fraction == Decimal("1")


def test_barrier_status_values():
    assert BarrierStatus.OPEN.value == "open"
    assert BarrierStatus.HIT.value == "hit"


def test_exit_reason_values():
    assert ExitReason.STOP_LOSS.value == "stop_loss"
    assert ExitReason.TAKE_PROFIT.value == "take_profit"
    assert ExitReason.TIME_EXIT.value == "time_exit"
    assert ExitReason.TRAILING_STOP.value == "trailing_stop"
    assert ExitReason.BREAK_EVEN_STOP.value == "break_even_stop"
    assert ExitReason.SIGNAL.value == "signal"
    assert ExitReason.PARTIAL_TAKE_PROFIT.value == "partial_take_profit"


# --- TripleBarrier stop loss tests ---


def test_stop_loss_long():
    config = BarrierConfig(stop_loss_pct=Decimal("5"))
    barrier = TripleBarrier(btc_pair, Decimal("50000"), _dt(), is_long=True, config=config)

    # Price above stop: no hit.
    result = barrier.check(Decimal("48000"), _dt(1, 13))
    assert not result.hit

    # Price at exactly 5% below entry: hit.
    result = barrier.check(Decimal("47500"), _dt(1, 14))
    assert result.hit
    assert result.reason == ExitReason.STOP_LOSS


def test_stop_loss_short():
    config = BarrierConfig(stop_loss_pct=Decimal("5"))
    barrier = TripleBarrier(btc_pair, Decimal("50000"), _dt(), is_long=False, config=config)

    # Price below entry (profit): no hit.
    result = barrier.check(Decimal("48000"), _dt(1, 13))
    assert not result.hit

    # Price 5% above entry: hit.
    result = barrier.check(Decimal("52500"), _dt(1, 14))
    assert result.hit
    assert result.reason == ExitReason.STOP_LOSS


# --- Take profit tests ---


def test_take_profit_long():
    config = BarrierConfig(take_profit_pct=Decimal("10"))
    barrier = TripleBarrier(btc_pair, Decimal("50000"), _dt(), is_long=True, config=config)

    result = barrier.check(Decimal("54000"), _dt(1, 13))
    assert not result.hit

    result = barrier.check(Decimal("55000"), _dt(1, 14))
    assert result.hit
    assert result.reason == ExitReason.TAKE_PROFIT


def test_take_profit_short():
    config = BarrierConfig(take_profit_pct=Decimal("10"))
    barrier = TripleBarrier(btc_pair, Decimal("50000"), _dt(), is_long=False, config=config)

    result = barrier.check(Decimal("46000"), _dt(1, 13))
    assert not result.hit

    result = barrier.check(Decimal("45000"), _dt(1, 14))
    assert result.hit
    assert result.reason == ExitReason.TAKE_PROFIT


# --- Time barrier tests ---


def test_time_barrier():
    config = BarrierConfig(time_limit=datetime.timedelta(hours=24))
    barrier = TripleBarrier(btc_pair, Decimal("50000"), _dt(1, 12), is_long=True, config=config)

    result = barrier.check(Decimal("50000"), _dt(1, 23))
    assert not result.hit

    result = barrier.check(Decimal("50000"), _dt(2, 12))
    assert result.hit
    assert result.reason == ExitReason.TIME_EXIT


# --- Trailing stop tests ---


def test_trailing_stop_long():
    config = BarrierConfig(trailing_stop_pct=Decimal("3"))
    barrier = TripleBarrier(btc_pair, Decimal("50000"), _dt(), is_long=True, config=config)

    # Price goes up to 55000.
    result = barrier.check(Decimal("55000"), _dt(1, 13))
    assert not result.hit
    assert barrier.peak_price == Decimal("55000")

    # Price drops but not enough for trailing stop.
    result = barrier.check(Decimal("54000"), _dt(1, 14))
    assert not result.hit

    # Price drops 3% from peak (55000 * 0.97 = 53350).
    result = barrier.check(Decimal("53000"), _dt(1, 15))
    assert result.hit
    assert result.reason == ExitReason.TRAILING_STOP


def test_trailing_stop_short():
    config = BarrierConfig(trailing_stop_pct=Decimal("3"))
    barrier = TripleBarrier(btc_pair, Decimal("50000"), _dt(), is_long=False, config=config)

    # Price goes down to 45000 (profit for short).
    result = barrier.check(Decimal("45000"), _dt(1, 13))
    assert not result.hit
    assert barrier.peak_price == Decimal("45000")

    # Price bounces up 3%+ from trough.
    result = barrier.check(Decimal("46500"), _dt(1, 14))
    assert result.hit
    assert result.reason == ExitReason.TRAILING_STOP


# --- Break-even tests ---


def test_break_even_arming():
    config = BarrierConfig(break_even_pct=Decimal("2"))
    barrier = TripleBarrier(btc_pair, Decimal("50000"), _dt(), is_long=True, config=config)

    assert not barrier.break_even_armed

    # Not enough profit to arm.
    barrier.check(Decimal("50500"), _dt(1, 13))
    assert not barrier.break_even_armed

    # 2% profit: arm break-even.
    barrier.check(Decimal("51000"), _dt(1, 14))
    assert barrier.break_even_armed

    # Price falls back to entry: break-even stop triggered.
    result = barrier.check(Decimal("50000"), _dt(1, 15))
    assert result.hit
    assert result.reason == ExitReason.BREAK_EVEN_STOP


def test_break_even_not_triggered_when_above():
    config = BarrierConfig(break_even_pct=Decimal("2"))
    barrier = TripleBarrier(btc_pair, Decimal("50000"), _dt(), is_long=True, config=config)

    barrier.check(Decimal("51000"), _dt(1, 14))  # Arm it.
    assert barrier.break_even_armed

    # Still above entry: no trigger.
    result = barrier.check(Decimal("50500"), _dt(1, 15))
    assert not result.hit


# --- Partial take profit tests ---


def test_partial_take_profit():
    config = BarrierConfig(
        partial_take_profit_pct=Decimal("5"),
        partial_take_profit_fraction=Decimal("0.5"),
        take_profit_pct=Decimal("10"),
    )
    barrier = TripleBarrier(btc_pair, Decimal("50000"), _dt(), is_long=True, config=config)

    assert not barrier.partial_taken

    # 5% profit: partial take profit.
    result = barrier.check(Decimal("52500"), _dt(1, 13))
    assert result.hit
    assert result.reason == ExitReason.PARTIAL_TAKE_PROFIT
    assert result.exit_fraction == Decimal("0.5")
    assert barrier.partial_taken

    # Second check at same level: partial already taken, no trigger.
    result = barrier.check(Decimal("52500"), _dt(1, 14))
    assert not result.hit

    # 10% profit: full take profit.
    result = barrier.check(Decimal("55000"), _dt(1, 15))
    assert result.hit
    assert result.reason == ExitReason.TAKE_PROFIT


# --- Combined barrier tests ---


def test_combined_stop_and_take_profit():
    config = BarrierConfig(stop_loss_pct=Decimal("5"), take_profit_pct=Decimal("10"))
    barrier = TripleBarrier(btc_pair, Decimal("50000"), _dt(), is_long=True, config=config)

    # Within range.
    result = barrier.check(Decimal("52000"), _dt(1, 13))
    assert not result.hit

    # Take profit hit first.
    result = barrier.check(Decimal("55000"), _dt(1, 14))
    assert result.hit
    assert result.reason == ExitReason.TAKE_PROFIT


def test_all_barriers_none():
    config = BarrierConfig()
    barrier = TripleBarrier(btc_pair, Decimal("50000"), _dt(), is_long=True, config=config)
    result = barrier.check(Decimal("0"), _dt(2))
    assert not result.hit


def test_barrier_properties():
    config = BarrierConfig(stop_loss_pct=Decimal("5"))
    barrier = TripleBarrier(btc_pair, Decimal("50000"), _dt(), is_long=True, config=config)
    assert barrier.pair == btc_pair
    assert barrier.entry_price == Decimal("50000")
    assert barrier.entry_dt == _dt()
    assert barrier.is_long
    assert barrier.config is config


def test_triple_barrier_take_profit_before_partial():
    """If take_profit_pct == partial_take_profit_pct, partial fires first."""
    config = BarrierConfig(
        partial_take_profit_pct=Decimal("10"),
        take_profit_pct=Decimal("10"),
    )
    barrier = TripleBarrier(btc_pair, Decimal("50000"), _dt(), is_long=True, config=config)
    result = barrier.check(Decimal("55000"), _dt(1, 13))
    assert result.hit
    assert result.reason == ExitReason.PARTIAL_TAKE_PROFIT


def test_entry_price_zero():
    config = BarrierConfig(stop_loss_pct=Decimal("5"))
    barrier = TripleBarrier(btc_pair, Decimal("0"), _dt(), is_long=True, config=config)
    result = barrier.check(Decimal("100"), _dt(1, 13))
    assert not result.hit


def test_trailing_stop_short_zero_trough():
    config = BarrierConfig(trailing_stop_pct=Decimal("3"))
    barrier = TripleBarrier(btc_pair, Decimal("50000"), _dt(), is_long=False, config=config)
    # Force trough to 0 by checking price 0.
    barrier.check(Decimal("0"), _dt(1, 13))
    result = barrier.check(Decimal("100"), _dt(1, 14))
    assert not result.hit  # Can't compute trailing with zero trough.
