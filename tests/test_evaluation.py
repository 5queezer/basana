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
from basana.core.evaluation import (
    EvaluationReport,
    FoldResult,
    WindowSpec,
    build_report,
    format_report,
    generate_expanding_windows,
    generate_sliding_windows,
    pair_windows,
)
from basana.core.ledger.types import EquitySnapshot, PerformanceMetrics, TradeRecord

utc = tz.UTC
btc_pair = bs.Pair("BTC", "USD")

_ZERO = Decimal(0)


def _dt(day=1, hour=0):
    return datetime.datetime(2026, 1, day, hour, 0, 0, tzinfo=utc)


def _empty_metrics():
    return PerformanceMetrics(
        total_trades=0, winning_trades=0, losing_trades=0,
        win_rate=_ZERO, total_pnl=_ZERO, avg_pnl=_ZERO,
        profit_factor=None, expectancy=_ZERO, max_drawdown=_ZERO,
        sharpe_ratio=None, sortino_ratio=None, calmar_ratio=None,
        avg_win=_ZERO, avg_loss=_ZERO,
    )


def _sample_metrics(trades=5, pnl=Decimal("1000")):
    return PerformanceMetrics(
        total_trades=trades, winning_trades=3, losing_trades=2,
        win_rate=Decimal("0.6"), total_pnl=pnl, avg_pnl=pnl / trades,
        profit_factor=Decimal("1.5"), expectancy=Decimal("200"),
        max_drawdown=Decimal("0.05"),
        sharpe_ratio=Decimal("1.5"), sortino_ratio=Decimal("2.0"),
        calmar_ratio=Decimal("3.0"),
        avg_win=Decimal("500"), avg_loss=Decimal("250"),
    )


# --- WindowSpec tests ---


def test_window_spec_frozen():
    w = WindowSpec(start=_dt(1), end=_dt(10))
    try:
        w.start = _dt(2)  # type: ignore[misc]
        assert False, "Should have raised"
    except AttributeError:
        pass


def test_window_spec_label():
    w = WindowSpec(start=_dt(1), end=_dt(10), label="train")
    assert w.label == "train"


def test_window_spec_defaults():
    w = WindowSpec(start=_dt(1), end=_dt(10))
    assert w.label is None


# --- Expanding windows ---


def test_expanding_windows():
    windows = generate_expanding_windows(
        start=_dt(1),
        end=_dt(31),
        test_duration=datetime.timedelta(days=5),
        min_train_duration=datetime.timedelta(days=10),
    )
    pairs = pair_windows(windows)
    assert len(pairs) >= 1

    # First fold: train 10 days, test 5 days.
    train, test = pairs[0]
    assert train.label == "train"
    assert test.label == "test"
    assert train.start == _dt(1)
    assert train.end == _dt(11)
    assert test.start == _dt(11)
    assert test.end == _dt(16)

    # Second fold: expanding train, same test size.
    if len(pairs) > 1:
        train2, test2 = pairs[1]
        assert train2.start == _dt(1)  # Anchored.
        assert train2.end == _dt(16)  # Expanded.
        assert test2.end - test2.start == datetime.timedelta(days=5)


def test_expanding_windows_custom_step():
    windows = generate_expanding_windows(
        start=_dt(1),
        end=_dt(31),
        test_duration=datetime.timedelta(days=5),
        min_train_duration=datetime.timedelta(days=10),
        step=datetime.timedelta(days=3),
    )
    pairs = pair_windows(windows)
    assert len(pairs) >= 2

    # Step is 3 days instead of test_duration (5).
    train1, _ = pairs[0]
    train2, _ = pairs[1]
    assert train2.end - train1.end == datetime.timedelta(days=3)


def test_expanding_windows_too_short():
    windows = generate_expanding_windows(
        start=_dt(1),
        end=_dt(5),
        test_duration=datetime.timedelta(days=5),
        min_train_duration=datetime.timedelta(days=10),
    )
    assert len(windows) == 0


# --- Sliding windows ---


def test_sliding_windows():
    windows = generate_sliding_windows(
        start=_dt(1),
        end=_dt(31),
        train_duration=datetime.timedelta(days=10),
        test_duration=datetime.timedelta(days=5),
    )
    pairs = pair_windows(windows)
    assert len(pairs) >= 1

    train, test = pairs[0]
    assert train.start == _dt(1)
    assert train.end == _dt(11)
    assert test.start == _dt(11)
    assert test.end == _dt(16)

    if len(pairs) > 1:
        train2, _ = pairs[1]
        # Sliding: train start moves forward by step (= test_duration).
        assert train2.start == _dt(6)


def test_sliding_windows_custom_step():
    windows = generate_sliding_windows(
        start=_dt(1),
        end=_dt(31),
        train_duration=datetime.timedelta(days=10),
        test_duration=datetime.timedelta(days=5),
        step=datetime.timedelta(days=2),
    )
    pairs = pair_windows(windows)
    assert len(pairs) >= 2
    train1, _ = pairs[0]
    train2, _ = pairs[1]
    assert train2.start - train1.start == datetime.timedelta(days=2)


def test_sliding_windows_too_short():
    windows = generate_sliding_windows(
        start=_dt(1),
        end=_dt(5),
        train_duration=datetime.timedelta(days=10),
        test_duration=datetime.timedelta(days=5),
    )
    assert len(windows) == 0


# --- pair_windows ---


def test_pair_windows_empty():
    assert pair_windows([]) == []


def test_pair_windows_single():
    # Odd number: last window is unpaired.
    w = WindowSpec(start=_dt(1), end=_dt(10), label="train")
    assert pair_windows([w]) == []


# --- FoldResult tests ---


def test_fold_result_frozen():
    fold = FoldResult(
        fold_index=0,
        train_window=WindowSpec(start=_dt(1), end=_dt(10)),
        test_window=WindowSpec(start=_dt(10), end=_dt(15)),
        train_metrics=_empty_metrics(),
        test_metrics=_empty_metrics(),
    )
    try:
        fold.fold_index = 1  # type: ignore[misc]
        assert False, "Should have raised"
    except AttributeError:
        pass


# --- EvaluationReport tests ---


def test_evaluation_report_frozen():
    report = EvaluationReport(
        strategy_name="test",
        folds=[],
        aggregate_oos_metrics=_empty_metrics(),
    )
    try:
        report.strategy_name = "other"  # type: ignore[misc]
        assert False, "Should have raised"
    except AttributeError:
        pass


# --- build_report ---


def test_build_report():
    folds = [
        FoldResult(
            fold_index=0,
            train_window=WindowSpec(start=_dt(1), end=_dt(10)),
            test_window=WindowSpec(start=_dt(10), end=_dt(15)),
            train_metrics=_sample_metrics(),
            test_metrics=_sample_metrics(pnl=Decimal("500")),
        ),
    ]
    trades = [
        TradeRecord(
            trade_id="1", pair=btc_pair, entry_dt=_dt(10), exit_dt=_dt(12),
            signed_qty=Decimal("1"), entry_price=Decimal("50000"),
            exit_price=Decimal("51000"), realized_pnl=Decimal("1000"),
            return_pct=Decimal("0.02"),
        ),
    ]
    curve = [
        EquitySnapshot(when=_dt(10), equity=Decimal("100000")),
        EquitySnapshot(when=_dt(15), equity=Decimal("101000")),
    ]
    report = build_report("sma_cross", folds, trades, curve)
    assert report.strategy_name == "sma_cross"
    assert len(report.folds) == 1
    assert report.aggregate_oos_metrics.total_trades == 1


# --- format_report ---


def test_format_report():
    folds = [
        FoldResult(
            fold_index=0,
            train_window=WindowSpec(start=_dt(1), end=_dt(10)),
            test_window=WindowSpec(start=_dt(10), end=_dt(15)),
            train_metrics=_sample_metrics(),
            test_metrics=_sample_metrics(pnl=Decimal("500")),
        ),
    ]
    report = EvaluationReport(
        strategy_name="test_strategy",
        folds=folds,
        aggregate_oos_metrics=_sample_metrics(),
    )
    text = format_report(report)
    assert "test_strategy" in text
    assert "Fold 0" in text
    assert "Win rate" in text
    assert "Sharpe" in text
    assert "N/A" not in text  # All metrics have values.


def test_format_report_empty_metrics():
    report = EvaluationReport(
        strategy_name="empty",
        folds=[],
        aggregate_oos_metrics=_empty_metrics(),
    )
    text = format_report(report)
    assert "empty" in text
    assert "N/A" in text  # Sharpe/Sortino/Calmar are None.
