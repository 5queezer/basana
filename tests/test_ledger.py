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
from basana.core.ledger import (
    EquitySnapshot,
    PerformanceMetrics,
    TradingLedger,
    TradeRecord,
    calculate_max_drawdown,
    calculate_metrics,
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
)

utc = tz.UTC
btc_pair = bs.Pair("BTC", "USD")
eth_pair = bs.Pair("ETH", "USD")


def _dt(day=1, hour=12, minute=0):
    return datetime.datetime(2026, 1, day, hour, minute, 0, tzinfo=utc)


# --- TradeRecord tests ---


def test_trade_record_frozen():
    tr = TradeRecord(
        trade_id="abc",
        pair=btc_pair,
        entry_dt=_dt(1),
        exit_dt=_dt(2),
        signed_qty=Decimal("1"),
        entry_price=Decimal("50000"),
        exit_price=Decimal("55000"),
        realized_pnl=Decimal("5000"),
        return_pct=Decimal("0.1"),
        reason="signal",
    )
    try:
        tr.realized_pnl = Decimal(0)  # type: ignore[misc]
        assert False, "Should have raised"
    except AttributeError:
        pass


def test_equity_snapshot_frozen():
    snap = EquitySnapshot(when=_dt(), equity=Decimal("10000"))
    try:
        snap.equity = Decimal(0)  # type: ignore[misc]
        assert False, "Should have raised"
    except AttributeError:
        pass


# --- TradingLedger basic tests ---


def test_ledger_initial_state():
    ledger = TradingLedger(initial_cash=Decimal("10000"))
    assert ledger.cash == Decimal("10000")
    assert ledger.get_equity() == Decimal("10000")
    assert ledger.get_unrealized_pnl() == Decimal(0)
    assert len(ledger.trades) == 0
    assert len(ledger.equity_curve) == 0
    assert len(ledger.open_positions) == 0


def test_ledger_open_position():
    ledger = TradingLedger(initial_cash=Decimal("100000"))
    result = ledger.record_fill(btc_pair, Decimal("1"), Decimal("50000"), _dt())
    assert result is None  # Opening, no trade record.
    assert btc_pair in ledger.open_positions
    assert ledger.open_positions[btc_pair] == Decimal("1")


def test_ledger_close_position():
    ledger = TradingLedger(initial_cash=Decimal("100000"))
    ledger.record_fill(btc_pair, Decimal("1"), Decimal("50000"), _dt(1))
    trade = ledger.record_fill(btc_pair, Decimal("-1"), Decimal("55000"), _dt(2), reason="take_profit")
    assert trade is not None
    assert trade.realized_pnl == Decimal("5000")
    assert trade.return_pct == Decimal("0.1")
    assert trade.reason == "take_profit"
    assert trade.entry_price == Decimal("50000")
    assert trade.exit_price == Decimal("55000")
    assert len(ledger.trades) == 1
    assert btc_pair not in ledger.open_positions
    assert ledger.cash == Decimal("105000")


def test_ledger_partial_close():
    ledger = TradingLedger(initial_cash=Decimal("100000"))
    ledger.record_fill(btc_pair, Decimal("2"), Decimal("50000"), _dt(1))
    trade = ledger.record_fill(btc_pair, Decimal("-1"), Decimal("55000"), _dt(2))
    assert trade is not None
    assert trade.realized_pnl == Decimal("5000")
    assert ledger.open_positions[btc_pair] == Decimal("1")


def test_ledger_add_to_position():
    ledger = TradingLedger(initial_cash=Decimal("100000"))
    ledger.record_fill(btc_pair, Decimal("1"), Decimal("50000"), _dt(1))
    result = ledger.record_fill(btc_pair, Decimal("1"), Decimal("60000"), _dt(2))
    assert result is None  # Adding, no trade record.
    assert ledger.open_positions[btc_pair] == Decimal("2")


def test_ledger_flip_position():
    ledger = TradingLedger(initial_cash=Decimal("100000"))
    ledger.record_fill(btc_pair, Decimal("1"), Decimal("50000"), _dt(1))
    trade = ledger.record_fill(btc_pair, Decimal("-2"), Decimal("55000"), _dt(2))
    assert trade is not None
    assert trade.realized_pnl == Decimal("5000")
    # Flipped to short 1.
    assert ledger.open_positions[btc_pair] == Decimal("-1")


def test_ledger_short_position():
    ledger = TradingLedger(initial_cash=Decimal("100000"))
    ledger.record_fill(btc_pair, Decimal("-1"), Decimal("50000"), _dt(1))
    trade = ledger.record_fill(btc_pair, Decimal("1"), Decimal("45000"), _dt(2))
    assert trade is not None
    assert trade.realized_pnl == Decimal("5000")
    assert btc_pair not in ledger.open_positions


def test_ledger_unrealized_pnl():
    ledger = TradingLedger(initial_cash=Decimal("100000"))
    ledger.record_fill(btc_pair, Decimal("1"), Decimal("50000"), _dt())
    ledger.update_price(btc_pair, Decimal("55000"))
    assert ledger.get_unrealized_pnl() == Decimal("5000")
    assert ledger.get_equity() == Decimal("105000")


def test_ledger_update_price_no_position():
    ledger = TradingLedger(initial_cash=Decimal("10000"))
    # Updating price for a pair with no position should not error.
    ledger.update_price(btc_pair, Decimal("50000"))
    assert ledger.get_equity() == Decimal("10000")


def test_ledger_multiple_positions():
    ledger = TradingLedger(initial_cash=Decimal("100000"))
    ledger.record_fill(btc_pair, Decimal("1"), Decimal("50000"), _dt())
    ledger.record_fill(eth_pair, Decimal("10"), Decimal("3000"), _dt())
    assert len(ledger.open_positions) == 2


# --- Equity snapshots ---


def test_ledger_take_snapshot():
    ledger = TradingLedger(initial_cash=Decimal("10000"))
    snap = ledger.take_snapshot(_dt())
    assert snap.equity == Decimal("10000")
    assert snap.when == _dt()
    assert len(ledger.equity_curve) == 1


def test_ledger_auto_snapshot():
    ledger = TradingLedger(
        initial_cash=Decimal("100000"),
        equity_snapshot_interval=datetime.timedelta(hours=1),
    )
    # First fill triggers first snapshot.
    ledger.record_fill(btc_pair, Decimal("1"), Decimal("50000"), _dt(1, 12, 0))
    assert len(ledger.equity_curve) == 1

    # Fill within interval does not trigger snapshot.
    ledger.update_price(btc_pair, Decimal("51000"), _dt(1, 12, 30))
    assert len(ledger.equity_curve) == 1

    # Fill after interval triggers snapshot.
    ledger.update_price(btc_pair, Decimal("52000"), _dt(1, 13, 1))
    assert len(ledger.equity_curve) == 2


# --- Daily/weekly summaries ---


def test_ledger_daily_pnl():
    ledger = TradingLedger(initial_cash=Decimal("100000"))
    ledger.record_fill(btc_pair, Decimal("1"), Decimal("50000"), _dt(1))
    ledger.record_fill(btc_pair, Decimal("-1"), Decimal("55000"), _dt(1))
    ledger.record_fill(btc_pair, Decimal("1"), Decimal("55000"), _dt(2))
    ledger.record_fill(btc_pair, Decimal("-1"), Decimal("53000"), _dt(2))
    daily = ledger.get_daily_pnl()
    assert daily[datetime.date(2026, 1, 1)] == Decimal("5000")
    assert daily[datetime.date(2026, 1, 2)] == Decimal("-2000")


def test_ledger_weekly_pnl():
    ledger = TradingLedger(initial_cash=Decimal("100000"))
    ledger.record_fill(btc_pair, Decimal("1"), Decimal("50000"), _dt(1))
    ledger.record_fill(btc_pair, Decimal("-1"), Decimal("55000"), _dt(2))
    weekly = ledger.get_weekly_pnl()
    assert len(weekly) == 1
    pnl = list(weekly.values())[0]
    assert pnl == Decimal("5000")


# --- Metrics calculation ---


def test_calculate_max_drawdown_empty():
    assert calculate_max_drawdown([]) == Decimal(0)


def test_calculate_max_drawdown_single():
    assert calculate_max_drawdown([EquitySnapshot(_dt(), Decimal("10000"))]) == Decimal(0)


def test_calculate_max_drawdown():
    curve = [
        EquitySnapshot(_dt(1), Decimal("10000")),
        EquitySnapshot(_dt(2), Decimal("12000")),
        EquitySnapshot(_dt(3), Decimal("9000")),  # 25% drawdown from 12000.
        EquitySnapshot(_dt(4), Decimal("11000")),
    ]
    dd = calculate_max_drawdown(curve)
    assert dd == Decimal("0.25")


def test_calculate_max_drawdown_no_drawdown():
    curve = [
        EquitySnapshot(_dt(1), Decimal("10000")),
        EquitySnapshot(_dt(2), Decimal("11000")),
        EquitySnapshot(_dt(3), Decimal("12000")),
    ]
    assert calculate_max_drawdown(curve) == Decimal(0)


def test_calculate_sharpe_insufficient_data():
    assert calculate_sharpe_ratio([]) is None
    assert calculate_sharpe_ratio([EquitySnapshot(_dt(), Decimal("10000"))]) is None


def test_calculate_sharpe_ratio():
    curve = [
        EquitySnapshot(_dt(1), Decimal("10000")),
        EquitySnapshot(_dt(2), Decimal("10100")),
        EquitySnapshot(_dt(3), Decimal("10200")),
        EquitySnapshot(_dt(4), Decimal("10300")),
    ]
    sharpe = calculate_sharpe_ratio(curve)
    assert sharpe is not None
    assert sharpe > 0


def test_calculate_sharpe_zero_std():
    # All same equity = zero std dev.
    curve = [
        EquitySnapshot(_dt(1), Decimal("10000")),
        EquitySnapshot(_dt(2), Decimal("10000")),
        EquitySnapshot(_dt(3), Decimal("10000")),
    ]
    assert calculate_sharpe_ratio(curve) is None


def test_calculate_sortino_insufficient_data():
    assert calculate_sortino_ratio([]) is None
    assert calculate_sortino_ratio([EquitySnapshot(_dt(), Decimal("10000"))]) is None


def test_calculate_sortino_no_downside():
    # All positive returns = no downside.
    curve = [
        EquitySnapshot(_dt(1), Decimal("10000")),
        EquitySnapshot(_dt(2), Decimal("10100")),
        EquitySnapshot(_dt(3), Decimal("10200")),
    ]
    assert calculate_sortino_ratio(curve) is None


def test_calculate_sortino_ratio():
    curve = [
        EquitySnapshot(_dt(1), Decimal("10000")),
        EquitySnapshot(_dt(2), Decimal("10100")),
        EquitySnapshot(_dt(3), Decimal("9900")),
        EquitySnapshot(_dt(4), Decimal("10200")),
    ]
    sortino = calculate_sortino_ratio(curve)
    assert sortino is not None


def test_calculate_metrics_empty():
    metrics = calculate_metrics([], [])
    assert metrics.total_trades == 0
    assert metrics.win_rate == Decimal(0)
    assert metrics.sharpe_ratio is None


def test_calculate_metrics_with_trades():
    trades = [
        TradeRecord(
            trade_id="1", pair=btc_pair, entry_dt=_dt(1), exit_dt=_dt(2),
            signed_qty=Decimal("1"), entry_price=Decimal("50000"), exit_price=Decimal("55000"),
            realized_pnl=Decimal("5000"), return_pct=Decimal("0.1"),
        ),
        TradeRecord(
            trade_id="2", pair=btc_pair, entry_dt=_dt(3), exit_dt=_dt(4),
            signed_qty=Decimal("1"), entry_price=Decimal("55000"), exit_price=Decimal("53000"),
            realized_pnl=Decimal("-2000"), return_pct=Decimal("-0.0364"),
        ),
        TradeRecord(
            trade_id="3", pair=eth_pair, entry_dt=_dt(5), exit_dt=_dt(6),
            signed_qty=Decimal("10"), entry_price=Decimal("3000"), exit_price=Decimal("3200"),
            realized_pnl=Decimal("2000"), return_pct=Decimal("0.0667"),
        ),
    ]
    curve = [
        EquitySnapshot(_dt(1), Decimal("100000")),
        EquitySnapshot(_dt(2), Decimal("105000")),
        EquitySnapshot(_dt(3), Decimal("105000")),
        EquitySnapshot(_dt(4), Decimal("103000")),
        EquitySnapshot(_dt(5), Decimal("103000")),
        EquitySnapshot(_dt(6), Decimal("105000")),
    ]
    metrics = calculate_metrics(trades, curve)
    assert metrics.total_trades == 3
    assert metrics.winning_trades == 2
    assert metrics.losing_trades == 1
    assert metrics.total_pnl == Decimal("5000")
    assert metrics.profit_factor is not None
    assert metrics.profit_factor == Decimal("3.5")  # 7000 / 2000.
    assert metrics.max_drawdown > 0
    assert metrics.sharpe_ratio is not None
    assert metrics.calmar_ratio is not None


def test_calculate_metrics_all_winners():
    trades = [
        TradeRecord(
            trade_id="1", pair=btc_pair, entry_dt=_dt(1), exit_dt=_dt(2),
            signed_qty=Decimal("1"), entry_price=Decimal("50000"), exit_price=Decimal("55000"),
            realized_pnl=Decimal("5000"), return_pct=Decimal("0.1"),
        ),
    ]
    curve = [
        EquitySnapshot(_dt(1), Decimal("100000")),
        EquitySnapshot(_dt(2), Decimal("105000")),
    ]
    metrics = calculate_metrics(trades, curve)
    assert metrics.win_rate == Decimal("1")
    assert metrics.profit_factor is None  # No losses.
    assert metrics.avg_loss == Decimal(0)


def test_calculate_metrics_no_drawdown():
    trades = [
        TradeRecord(
            trade_id="1", pair=btc_pair, entry_dt=_dt(1), exit_dt=_dt(2),
            signed_qty=Decimal("1"), entry_price=Decimal("50000"), exit_price=Decimal("55000"),
            realized_pnl=Decimal("5000"), return_pct=Decimal("0.1"),
        ),
    ]
    curve = [
        EquitySnapshot(_dt(1), Decimal("100000")),
        EquitySnapshot(_dt(2), Decimal("105000")),
    ]
    metrics = calculate_metrics(trades, curve)
    assert metrics.calmar_ratio is None  # No drawdown.


# --- Ledger integrated metrics ---


def test_ledger_calculate_metrics():
    ledger = TradingLedger(initial_cash=Decimal("100000"))
    ledger.take_snapshot(_dt(1))
    ledger.record_fill(btc_pair, Decimal("1"), Decimal("50000"), _dt(1))
    ledger.record_fill(btc_pair, Decimal("-1"), Decimal("55000"), _dt(2))
    ledger.take_snapshot(_dt(2))
    ledger.record_fill(btc_pair, Decimal("1"), Decimal("55000"), _dt(3))
    ledger.record_fill(btc_pair, Decimal("-1"), Decimal("53000"), _dt(4))
    ledger.take_snapshot(_dt(4))

    metrics = ledger.calculate_metrics()
    assert metrics.total_trades == 2
    assert metrics.winning_trades == 1
    assert metrics.losing_trades == 1
    assert metrics.total_pnl == Decimal("3000")


# --- PerformanceMetrics frozen ---


def test_performance_metrics_frozen():
    metrics = PerformanceMetrics(
        total_trades=0, winning_trades=0, losing_trades=0,
        win_rate=Decimal(0), total_pnl=Decimal(0), avg_pnl=Decimal(0),
        profit_factor=None, expectancy=Decimal(0), max_drawdown=Decimal(0),
        sharpe_ratio=None, sortino_ratio=None, calmar_ratio=None,
        avg_win=Decimal(0), avg_loss=Decimal(0),
    )
    try:
        metrics.total_trades = 1  # type: ignore[misc]
        assert False, "Should have raised"
    except AttributeError:
        pass
