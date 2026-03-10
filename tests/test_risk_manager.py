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
from basana.core.risk import (
    CorrelationBucketLimit,
    DailyLossCapLimit,
    DeploymentMode,
    MaxGrossExposureLimit,
    MaxPositionsLimit,
    PerTradeRiskSizer,
    PortfolioTracker,
    RiskManager,
)

utc = tz.UTC
btc_pair = bs.Pair("BTC", "USD")
eth_pair = bs.Pair("ETH", "USD")
sol_pair = bs.Pair("SOL", "USD")


def _make_signal(pair, position, when=None):
    if when is None:
        when = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=utc)
    return bs.TradingSignal(when, position, pair)


def _dt(day=1, hour=12):
    return datetime.datetime(2026, 1, day, hour, 0, 0, tzinfo=utc)


# --- PortfolioTracker tests ---


def test_portfolio_tracker_initial_state():
    tracker = PortfolioTracker(initial_cash=Decimal("10000"))
    snap = tracker.snapshot(_dt())
    assert snap.total_equity == Decimal("10000")
    assert snap.gross_exposure == Decimal(0)
    assert snap.net_exposure == Decimal(0)
    assert snap.realized_pnl_today == Decimal(0)
    assert snap.unrealized_pnl == Decimal(0)
    assert len(snap.positions) == 0


def test_portfolio_tracker_record_fill_open():
    tracker = PortfolioTracker(initial_cash=Decimal("10000"))
    tracker.record_fill(btc_pair, Decimal("1"), Decimal("50000"), _dt())
    snap = tracker.snapshot(_dt())
    assert len(snap.positions) == 1
    pos = snap.positions[btc_pair]
    assert pos.signed_qty == Decimal("1")
    assert pos.avg_entry_price == Decimal("50000")
    assert pos.notional_value == Decimal("50000")


def test_portfolio_tracker_record_fill_close_realized_pnl():
    tracker = PortfolioTracker(initial_cash=Decimal("10000"))
    tracker.record_fill(btc_pair, Decimal("1"), Decimal("50000"), _dt())
    # Close at higher price.
    tracker.record_fill(btc_pair, Decimal("-1"), Decimal("55000"), _dt())
    snap = tracker.snapshot(_dt())
    assert snap.realized_pnl_today == Decimal("5000")
    assert tracker.total_realized_pnl == Decimal("5000")
    assert tracker.cash == Decimal("15000")
    assert len(snap.positions) == 0  # Closed position excluded.


def test_portfolio_tracker_record_fill_partial_close():
    tracker = PortfolioTracker(initial_cash=Decimal("10000"))
    tracker.record_fill(btc_pair, Decimal("2"), Decimal("50000"), _dt())
    tracker.record_fill(btc_pair, Decimal("-1"), Decimal("55000"), _dt())
    snap = tracker.snapshot(_dt())
    assert snap.realized_pnl_today == Decimal("5000")
    pos = snap.positions[btc_pair]
    assert pos.signed_qty == Decimal("1")
    assert pos.avg_entry_price == Decimal("50000")  # Unchanged for partial close.


def test_portfolio_tracker_record_fill_add_to_position():
    tracker = PortfolioTracker(initial_cash=Decimal("10000"))
    tracker.record_fill(btc_pair, Decimal("1"), Decimal("50000"), _dt())
    tracker.record_fill(btc_pair, Decimal("1"), Decimal("60000"), _dt())
    snap = tracker.snapshot(_dt())
    pos = snap.positions[btc_pair]
    assert pos.signed_qty == Decimal("2")
    assert pos.avg_entry_price == Decimal("55000")  # Weighted average.


def test_portfolio_tracker_record_fill_flip_sides():
    tracker = PortfolioTracker(initial_cash=Decimal("10000"))
    tracker.record_fill(btc_pair, Decimal("1"), Decimal("50000"), _dt())
    # Sell 2 to flip from long 1 to short 1.
    tracker.record_fill(btc_pair, Decimal("-2"), Decimal("55000"), _dt())
    snap = tracker.snapshot(_dt())
    pos = snap.positions[btc_pair]
    assert pos.signed_qty == Decimal("-1")
    assert pos.avg_entry_price == Decimal("55000")
    # Realized from closing the long 1 at 55k (entry 50k) = 5000.
    assert snap.realized_pnl_today == Decimal("5000")


def test_portfolio_tracker_short_position():
    tracker = PortfolioTracker(initial_cash=Decimal("10000"))
    tracker.record_fill(btc_pair, Decimal("-1"), Decimal("50000"), _dt())
    snap = tracker.snapshot(_dt())
    pos = snap.positions[btc_pair]
    assert pos.signed_qty == Decimal("-1")
    # Close short at lower price = profit.
    tracker.record_fill(btc_pair, Decimal("1"), Decimal("45000"), _dt())
    snap = tracker.snapshot(_dt())
    assert snap.realized_pnl_today == Decimal("5000")


def test_portfolio_tracker_unrealized_pnl():
    tracker = PortfolioTracker(initial_cash=Decimal("10000"))
    tracker.record_fill(btc_pair, Decimal("1"), Decimal("50000"), _dt())
    tracker.update_price(btc_pair, Decimal("55000"))
    snap = tracker.snapshot(_dt())
    assert snap.unrealized_pnl == Decimal("5000")
    assert snap.total_equity == Decimal("15000")


def test_portfolio_tracker_daily_pnl_reset():
    tracker = PortfolioTracker(initial_cash=Decimal("10000"))
    tracker.record_fill(btc_pair, Decimal("1"), Decimal("50000"), _dt(day=1))
    tracker.record_fill(btc_pair, Decimal("-1"), Decimal("55000"), _dt(day=1))
    assert tracker.realized_pnl_today == Decimal("5000")
    # New day resets daily P&L.
    snap = tracker.snapshot(_dt(day=2))
    assert snap.realized_pnl_today == Decimal(0)
    assert tracker.total_realized_pnl == Decimal("5000")  # Cumulative stays.


def test_portfolio_tracker_multiple_positions():
    tracker = PortfolioTracker(initial_cash=Decimal("10000"))
    tracker.record_fill(btc_pair, Decimal("1"), Decimal("50000"), _dt())
    tracker.record_fill(eth_pair, Decimal("10"), Decimal("3000"), _dt())
    snap = tracker.snapshot(_dt())
    assert len(snap.positions) == 2
    assert snap.gross_exposure == Decimal("80000")  # 50000 + 30000.
    assert snap.net_exposure == Decimal("80000")  # Both long.


def test_portfolio_tracker_update_price():
    tracker = PortfolioTracker(initial_cash=Decimal("10000"))
    tracker.record_fill(btc_pair, Decimal("1"), Decimal("50000"), _dt())
    tracker.update_price(btc_pair, Decimal("60000"))
    snap = tracker.snapshot(_dt())
    pos = snap.positions[btc_pair]
    assert pos.current_price == Decimal("60000")
    assert pos.notional_value == Decimal("60000")


# --- MaxPositionsLimit tests ---


def test_max_positions_limit_allows_under_max():
    limit = MaxPositionsLimit(max_positions=2)
    tracker = PortfolioTracker(initial_cash=Decimal("10000"))
    tracker.record_fill(btc_pair, Decimal("1"), Decimal("50000"), _dt())
    snap = tracker.snapshot(_dt())
    signal = _make_signal(eth_pair, bs.Position.LONG)
    result = limit.check(signal, snap)
    assert result.approved


def test_max_positions_limit_blocks_over_max():
    limit = MaxPositionsLimit(max_positions=1)
    tracker = PortfolioTracker(initial_cash=Decimal("10000"))
    tracker.record_fill(btc_pair, Decimal("1"), Decimal("50000"), _dt())
    snap = tracker.snapshot(_dt())
    signal = _make_signal(eth_pair, bs.Position.LONG)
    result = limit.check(signal, snap)
    assert not result.approved
    assert "Max positions" in result.reason


def test_max_positions_limit_allows_close():
    limit = MaxPositionsLimit(max_positions=1)
    tracker = PortfolioTracker(initial_cash=Decimal("10000"))
    tracker.record_fill(btc_pair, Decimal("1"), Decimal("50000"), _dt())
    snap = tracker.snapshot(_dt())
    # Closing an existing position should always be allowed.
    signal = _make_signal(btc_pair, bs.Position.NEUTRAL)
    result = limit.check(signal, snap)
    assert result.approved


def test_max_positions_limit_allows_existing_pair():
    limit = MaxPositionsLimit(max_positions=1)
    tracker = PortfolioTracker(initial_cash=Decimal("10000"))
    tracker.record_fill(btc_pair, Decimal("1"), Decimal("50000"), _dt())
    snap = tracker.snapshot(_dt())
    # Adjusting an existing position should be allowed.
    signal = _make_signal(btc_pair, bs.Position.LONG)
    result = limit.check(signal, snap)
    assert result.approved


# --- MaxGrossExposureLimit tests ---


def test_max_gross_exposure_absolute():
    limit = MaxGrossExposureLimit(max_exposure=Decimal("100000"))
    tracker = PortfolioTracker(initial_cash=Decimal("200000"))
    tracker.record_fill(btc_pair, Decimal("2"), Decimal("50000"), _dt())
    tracker.update_price(btc_pair, Decimal("60000"))
    snap = tracker.snapshot(_dt())
    # Gross exposure = 120000 > 100000.
    signal = _make_signal(eth_pair, bs.Position.LONG)
    result = limit.check(signal, snap)
    assert not result.approved


def test_max_gross_exposure_percentage():
    limit = MaxGrossExposureLimit(max_exposure_pct=Decimal("100"))
    tracker = PortfolioTracker(initial_cash=Decimal("100000"))
    tracker.record_fill(btc_pair, Decimal("2"), Decimal("50000"), _dt())
    tracker.update_price(btc_pair, Decimal("60000"))
    snap = tracker.snapshot(_dt())
    # Equity = 100000 + 20000 unrealized = 120000.
    # Exposure = 120000 = 100% of equity -> at boundary but not over.
    result = limit.check(signal=_make_signal(eth_pair, bs.Position.LONG), portfolio=snap)
    assert result.approved

    # Push exposure over 100%.
    tracker.record_fill(eth_pair, Decimal("10"), Decimal("3000"), _dt())
    snap = tracker.snapshot(_dt())
    result = limit.check(signal=_make_signal(sol_pair, bs.Position.LONG), portfolio=snap)
    assert not result.approved


def test_max_gross_exposure_allows_under():
    limit = MaxGrossExposureLimit(max_exposure=Decimal("100000"))
    tracker = PortfolioTracker(initial_cash=Decimal("100000"))
    tracker.record_fill(btc_pair, Decimal("1"), Decimal("50000"), _dt())
    snap = tracker.snapshot(_dt())
    signal = _make_signal(eth_pair, bs.Position.LONG)
    result = limit.check(signal, snap)
    assert result.approved


# --- CorrelationBucketLimit tests ---


def test_correlation_bucket_limit_blocks():
    limit = CorrelationBucketLimit(
        buckets={"crypto_major": [btc_pair, eth_pair]},
        max_per_bucket=Decimal("50000"),
    )
    tracker = PortfolioTracker(initial_cash=Decimal("200000"))
    tracker.record_fill(btc_pair, Decimal("1"), Decimal("50000"), _dt())
    snap = tracker.snapshot(_dt())
    signal = _make_signal(eth_pair, bs.Position.LONG)
    result = limit.check(signal, snap)
    assert not result.approved
    assert "crypto_major" in result.reason


def test_correlation_bucket_limit_allows_different_bucket():
    limit = CorrelationBucketLimit(
        buckets={"crypto_major": [btc_pair, eth_pair]},
        max_per_bucket=Decimal("50000"),
    )
    tracker = PortfolioTracker(initial_cash=Decimal("200000"))
    tracker.record_fill(btc_pair, Decimal("1"), Decimal("50000"), _dt())
    snap = tracker.snapshot(_dt())
    # SOL is not in any bucket.
    signal = _make_signal(sol_pair, bs.Position.LONG)
    result = limit.check(signal, snap)
    assert result.approved


def test_correlation_bucket_limit_allows_close():
    limit = CorrelationBucketLimit(
        buckets={"crypto_major": [btc_pair, eth_pair]},
        max_per_bucket=Decimal("50000"),
    )
    tracker = PortfolioTracker(initial_cash=Decimal("200000"))
    tracker.record_fill(btc_pair, Decimal("1"), Decimal("50000"), _dt())
    snap = tracker.snapshot(_dt())
    signal = _make_signal(btc_pair, bs.Position.NEUTRAL)
    result = limit.check(signal, snap)
    assert result.approved


# --- DailyLossCapLimit tests ---


def test_daily_loss_cap_allows_within_limit():
    limit = DailyLossCapLimit(max_loss=Decimal("500"))
    tracker = PortfolioTracker(initial_cash=Decimal("10000"))
    tracker.record_fill(btc_pair, Decimal("1"), Decimal("50000"), _dt())
    tracker.record_fill(btc_pair, Decimal("-1"), Decimal("49800"), _dt())
    snap = tracker.snapshot(_dt())
    # Loss of 200, cap is 500.
    signal = _make_signal(eth_pair, bs.Position.LONG)
    result = limit.check(signal, snap)
    assert result.approved


def test_daily_loss_cap_blocks_over_limit():
    limit = DailyLossCapLimit(max_loss=Decimal("500"))
    tracker = PortfolioTracker(initial_cash=Decimal("10000"))
    tracker.record_fill(btc_pair, Decimal("1"), Decimal("50000"), _dt())
    tracker.record_fill(btc_pair, Decimal("-1"), Decimal("49000"), _dt())
    snap = tracker.snapshot(_dt())
    # Loss of 1000 > cap of 500.
    signal = _make_signal(eth_pair, bs.Position.LONG)
    result = limit.check(signal, snap)
    assert not result.approved
    assert "Daily loss cap" in result.reason


def test_daily_loss_cap_allows_close():
    limit = DailyLossCapLimit(max_loss=Decimal("500"))
    tracker = PortfolioTracker(initial_cash=Decimal("10000"))
    tracker.record_fill(btc_pair, Decimal("1"), Decimal("50000"), _dt())
    tracker.record_fill(btc_pair, Decimal("-1"), Decimal("49000"), _dt())
    snap = tracker.snapshot(_dt())
    # Over limit, but closing is always ok.
    tracker.record_fill(eth_pair, Decimal("10"), Decimal("3000"), _dt())
    snap = tracker.snapshot(_dt())
    signal = _make_signal(eth_pair, bs.Position.NEUTRAL)
    result = limit.check(signal, snap)
    assert result.approved


# --- PerTradeRiskSizer tests ---


def test_per_trade_risk_sizer():
    sizer = PerTradeRiskSizer(risk_pct=Decimal("1"))
    tracker = PortfolioTracker(initial_cash=Decimal("100000"))
    snap = tracker.snapshot(_dt())
    signal = _make_signal(btc_pair, bs.Position.LONG)
    result = sizer.check(signal, snap)
    assert result.approved
    assert signal.risk_sized_pct == Decimal("1")  # type: ignore[attr-defined]
    assert signal.risk_sized_amount == Decimal("1000")  # type: ignore[attr-defined]


# --- RiskManager integration tests ---


def test_risk_manager_passes_approved_signals(backtesting_dispatcher):
    async def impl():
        tracker = PortfolioTracker(initial_cash=Decimal("100000"))
        risk_mgr = RiskManager(
            backtesting_dispatcher,
            tracker,
            limits=[MaxPositionsLimit(max_positions=5)],
            mode=DeploymentMode.LIVE,
        )
        received = []

        async def on_signal(signal):
            received.append(signal)

        risk_mgr.subscribe_to_filtered_signals(on_signal)

        signal = _make_signal(btc_pair, bs.Position.LONG)
        await risk_mgr.on_trading_signal(signal)

        # Dispatch to deliver the queued event.
        await backtesting_dispatcher.run()

        assert len(received) == 1
        assert received[0] is signal

    asyncio.run(impl())


def test_risk_manager_blocks_rejected_signals(backtesting_dispatcher):
    async def impl():
        tracker = PortfolioTracker(initial_cash=Decimal("100000"))
        tracker.record_fill(btc_pair, Decimal("1"), Decimal("50000"), _dt())
        risk_mgr = RiskManager(
            backtesting_dispatcher,
            tracker,
            limits=[MaxPositionsLimit(max_positions=1)],
            mode=DeploymentMode.LIVE,
        )
        received = []

        async def on_signal(signal):
            received.append(signal)

        risk_mgr.subscribe_to_filtered_signals(on_signal)

        signal = _make_signal(eth_pair, bs.Position.LONG)
        await risk_mgr.on_trading_signal(signal)
        await backtesting_dispatcher.run()

        assert len(received) == 0

    asyncio.run(impl())


def test_risk_manager_monitor_mode_passes_through(backtesting_dispatcher):
    async def impl():
        tracker = PortfolioTracker(initial_cash=Decimal("100000"))
        tracker.record_fill(btc_pair, Decimal("1"), Decimal("50000"), _dt())
        risk_mgr = RiskManager(
            backtesting_dispatcher,
            tracker,
            limits=[MaxPositionsLimit(max_positions=1)],
            mode=DeploymentMode.MONITOR,
        )
        received = []

        async def on_signal(signal):
            received.append(signal)

        risk_mgr.subscribe_to_filtered_signals(on_signal)

        signal = _make_signal(eth_pair, bs.Position.LONG)
        await risk_mgr.on_trading_signal(signal)
        await backtesting_dispatcher.run()

        # MONITOR mode passes through even when limit is breached.
        assert len(received) == 1

    asyncio.run(impl())


def test_risk_manager_kill_switch_blocks(backtesting_dispatcher):
    async def impl():
        tracker = PortfolioTracker(initial_cash=Decimal("100000"))
        risk_mgr = RiskManager(
            backtesting_dispatcher,
            tracker,
            limits=[],
            mode=DeploymentMode.LIVE,
        )
        received = []

        async def on_signal(signal):
            received.append(signal)

        risk_mgr.subscribe_to_filtered_signals(on_signal)

        risk_mgr.activate_kill_switch("test emergency")
        assert risk_mgr.kill_switch_active
        assert risk_mgr.kill_switch_reason == "test emergency"

        signal = _make_signal(btc_pair, bs.Position.LONG)
        await risk_mgr.on_trading_signal(signal)
        await backtesting_dispatcher.run()
        assert len(received) == 0

    asyncio.run(impl())


def test_risk_manager_kill_switch_deactivate(backtesting_dispatcher):
    async def impl():
        tracker = PortfolioTracker(initial_cash=Decimal("100000"))
        risk_mgr = RiskManager(
            backtesting_dispatcher,
            tracker,
            limits=[],
            mode=DeploymentMode.LIVE,
        )
        received = []

        async def on_signal(signal):
            received.append(signal)

        risk_mgr.subscribe_to_filtered_signals(on_signal)

        risk_mgr.activate_kill_switch("test")
        risk_mgr.deactivate_kill_switch()
        assert not risk_mgr.kill_switch_active
        assert risk_mgr.kill_switch_reason is None

        signal = _make_signal(btc_pair, bs.Position.LONG)
        await risk_mgr.on_trading_signal(signal)
        await backtesting_dispatcher.run()
        assert len(received) == 1

    asyncio.run(impl())


def test_risk_manager_kill_switch_monitor_mode(backtesting_dispatcher):
    async def impl():
        tracker = PortfolioTracker(initial_cash=Decimal("100000"))
        risk_mgr = RiskManager(
            backtesting_dispatcher,
            tracker,
            limits=[],
            mode=DeploymentMode.MONITOR,
        )
        received = []

        async def on_signal(signal):
            received.append(signal)

        risk_mgr.subscribe_to_filtered_signals(on_signal)

        risk_mgr.activate_kill_switch("test")
        signal = _make_signal(btc_pair, bs.Position.LONG)
        await risk_mgr.on_trading_signal(signal)
        await backtesting_dispatcher.run()

        # MONITOR mode passes through even with kill switch.
        assert len(received) == 1

    asyncio.run(impl())


def test_risk_manager_on_bar_event(backtesting_dispatcher):
    async def impl():
        tracker = PortfolioTracker(initial_cash=Decimal("100000"))
        risk_mgr = RiskManager(backtesting_dispatcher, tracker)
        tracker.record_fill(btc_pair, Decimal("1"), Decimal("50000"), _dt())

        bar_event = bs.BarEvent(
            when=_dt(),
            bar=bs.Bar(
                begin=_dt(),
                pair=btc_pair,
                open=Decimal("50000"),
                high=Decimal("60000"),
                low=Decimal("49000"),
                close=Decimal("58000"),
                volume=Decimal("100"),
                duration=datetime.timedelta(days=1),
            ),
        )
        await risk_mgr.on_bar_event(bar_event)

        snap = tracker.snapshot(_dt())
        pos = snap.positions[btc_pair]
        assert pos.current_price == Decimal("58000")

    asyncio.run(impl())


def test_risk_manager_record_fill(backtesting_dispatcher):
    async def impl():
        tracker = PortfolioTracker(initial_cash=Decimal("10000"))
        risk_mgr = RiskManager(backtesting_dispatcher, tracker)
        risk_mgr.record_fill(btc_pair, Decimal("1"), Decimal("50000"), _dt())
        snap = tracker.snapshot(_dt())
        assert len(snap.positions) == 1
        assert snap.positions[btc_pair].signed_qty == Decimal("1")

    asyncio.run(impl())


def test_risk_manager_multiple_limits(backtesting_dispatcher):
    async def impl():
        tracker = PortfolioTracker(initial_cash=Decimal("100000"))
        risk_mgr = RiskManager(
            backtesting_dispatcher,
            tracker,
            limits=[
                MaxPositionsLimit(max_positions=5),
                MaxGrossExposureLimit(max_exposure=Decimal("200000")),
                DailyLossCapLimit(max_loss=Decimal("10000")),
            ],
            mode=DeploymentMode.LIVE,
        )
        received = []

        async def on_signal(signal):
            received.append(signal)

        risk_mgr.subscribe_to_filtered_signals(on_signal)

        signal = _make_signal(btc_pair, bs.Position.LONG)
        await risk_mgr.on_trading_signal(signal)
        await backtesting_dispatcher.run()
        assert len(received) == 1

    asyncio.run(impl())


def test_risk_manager_properties(backtesting_dispatcher):
    tracker = PortfolioTracker(initial_cash=Decimal("10000"))
    risk_mgr = RiskManager(
        backtesting_dispatcher,
        tracker,
        mode=DeploymentMode.PAPER,
    )
    assert risk_mgr.mode == DeploymentMode.PAPER
    assert risk_mgr.portfolio is tracker
    assert not risk_mgr.kill_switch_active


def test_portfolio_snapshot_frozen():
    tracker = PortfolioTracker(initial_cash=Decimal("10000"))
    snap = tracker.snapshot(_dt())
    # PortfolioSnapshot is a frozen dataclass.
    try:
        snap.total_equity = Decimal(0)  # type: ignore[misc]
        assert False, "Should have raised"
    except AttributeError:
        pass


def test_risk_check_result_frozen():
    from basana.core.risk.types import RiskCheckResult

    result = RiskCheckResult(approved=True, reason=None)
    try:
        result.approved = False  # type: ignore[misc]
        assert False, "Should have raised"
    except AttributeError:
        pass


def test_position_snapshot_frozen():
    from basana.core.risk.types import PositionSnapshot

    pos = PositionSnapshot(
        pair=btc_pair,
        signed_qty=Decimal("1"),
        avg_entry_price=Decimal("50000"),
        current_price=Decimal("50000"),
        unrealized_pnl=Decimal(0),
        notional_value=Decimal("50000"),
    )
    try:
        pos.signed_qty = Decimal(0)  # type: ignore[misc]
        assert False, "Should have raised"
    except AttributeError:
        pass
