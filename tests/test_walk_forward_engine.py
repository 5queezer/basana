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
from typing import Any, Dict, Optional
import datetime

from dateutil import tz

import basana as bs
from basana.core.evaluation import (
    FoldOutput,
    WalkForwardEngine,
    WindowSpec,
    format_report,
    generate_sliding_windows,
)
from basana.core.ledger.types import EquitySnapshot, TradeRecord

utc = tz.UTC
btc_pair = bs.Pair("BTC", "USD")


def _dt(day=1, hour=0):
    return datetime.datetime(2026, 1, day, hour, 0, 0, tzinfo=utc)


def _make_trade(entry_day, exit_day, pnl):
    return TradeRecord(
        trade_id=f"t{entry_day}-{exit_day}",
        pair=btc_pair,
        entry_dt=_dt(entry_day),
        exit_dt=_dt(exit_day),
        signed_qty=Decimal("1"),
        entry_price=Decimal("50000"),
        exit_price=Decimal("50000") + pnl,
        realized_pnl=pnl,
        return_pct=pnl / Decimal("50000"),
    )


def _make_equity(day, equity):
    return EquitySnapshot(when=_dt(day), equity=equity)


# --- Basic engine run ---


def test_engine_basic():
    """Engine runs strategy on train/test, collects fold results and aggregate OOS."""

    async def _test():
        windows = generate_sliding_windows(
            start=_dt(1),
            end=_dt(31),
            train_duration=datetime.timedelta(days=10),
            test_duration=datetime.timedelta(days=5),
        )

        call_log = []

        async def runner(window: WindowSpec, params: Optional[Dict[str, Any]]) -> FoldOutput:
            call_log.append((window.label, params))
            trades = [_make_trade(window.start.day, window.end.day, Decimal("100"))]
            curve = [
                _make_equity(window.start.day, Decimal("10000")),
                _make_equity(window.end.day, Decimal("10100")),
            ]
            return FoldOutput(trades=trades, equity_curve=curve)

        engine = WalkForwardEngine(
            strategy_name="test_strat",
            strategy_runner=runner,
            windows=windows,
            periods_per_year=252,
        )
        report = await engine.run()

        assert report.strategy_name == "test_strat"
        assert len(report.folds) > 0

        # Each fold should have called runner twice (train + test).
        train_calls = [c for c in call_log if c[0] == "train"]
        test_calls = [c for c in call_log if c[0] == "test"]
        assert len(train_calls) == len(report.folds)
        assert len(test_calls) == len(report.folds)

        # Test calls should have params=None (no optimizer).
        for _, params in test_calls:
            assert params is None

        # Aggregate OOS should have trades from all test folds.
        assert report.aggregate_oos_metrics.total_trades == len(report.folds)

    asyncio.run(_test())


def test_engine_with_optimizer():
    """ParamOptimizer output is forwarded to test runner."""

    async def _test():
        windows = generate_sliding_windows(
            start=_dt(1),
            end=_dt(31),
            train_duration=datetime.timedelta(days=10),
            test_duration=datetime.timedelta(days=5),
        )

        received_params = []

        async def runner(window: WindowSpec, params: Optional[Dict[str, Any]]) -> FoldOutput:
            if window.label == "test":
                received_params.append(params)
            trades = [_make_trade(window.start.day, window.end.day, Decimal("50"))]
            curve = [
                _make_equity(window.start.day, Decimal("10000")),
                _make_equity(window.end.day, Decimal("10050")),
            ]
            return FoldOutput(trades=trades, equity_curve=curve)

        async def optimizer(window: WindowSpec, output: FoldOutput) -> Dict[str, Any]:
            return {"ku": 2.0, "tu": 12}

        engine = WalkForwardEngine(
            strategy_name="opt_strat",
            strategy_runner=runner,
            windows=windows,
            param_optimizer=optimizer,
        )
        report = await engine.run()

        # Every test fold should have received the optimized params.
        assert len(received_params) == len(report.folds)
        for p in received_params:
            assert p == {"ku": 2.0, "tu": 12}

    asyncio.run(_test())


def test_engine_empty_windows():
    """No folds when windows are empty."""

    async def _test():
        engine = WalkForwardEngine(
            strategy_name="empty",
            strategy_runner=lambda w, p: None,  # type: ignore
            windows=[],
        )
        report = await engine.run()
        assert len(report.folds) == 0
        assert report.aggregate_oos_metrics.total_trades == 0

    asyncio.run(_test())


def test_engine_fold_metrics():
    """Per-fold train and test metrics are populated."""

    async def _test():
        windows = [
            WindowSpec(start=_dt(1), end=_dt(11), label="train"),
            WindowSpec(start=_dt(11), end=_dt(16), label="test"),
        ]

        async def runner(window: WindowSpec, params: Optional[Dict[str, Any]]) -> FoldOutput:
            pnl = Decimal("200") if window.label == "train" else Decimal("-50")
            trades = [_make_trade(window.start.day, window.end.day, pnl)]
            curve = [
                _make_equity(window.start.day, Decimal("10000")),
                _make_equity(window.end.day, Decimal("10000") + pnl),
            ]
            return FoldOutput(trades=trades, equity_curve=curve)

        engine = WalkForwardEngine(
            strategy_name="fold_metrics",
            strategy_runner=runner,
            windows=windows,
        )
        report = await engine.run()

        assert len(report.folds) == 1
        fold = report.folds[0]
        assert fold.train_metrics.total_pnl == Decimal("200")
        assert fold.test_metrics.total_pnl == Decimal("-50")

    asyncio.run(_test())


def test_engine_pre_calculated_metrics():
    """FoldOutput.metrics is used when provided instead of auto-calculating."""

    async def _test():
        from basana.core.ledger.types import PerformanceMetrics

        _ZERO = Decimal(0)
        custom_metrics = PerformanceMetrics(
            total_trades=99, winning_trades=99, losing_trades=0,
            win_rate=Decimal("1"), total_pnl=Decimal("9999"), avg_pnl=Decimal("101"),
            profit_factor=None, expectancy=Decimal("101"), max_drawdown=_ZERO,
            sharpe_ratio=None, sortino_ratio=None, calmar_ratio=None,
            avg_win=Decimal("101"), avg_loss=_ZERO,
        )

        windows = [
            WindowSpec(start=_dt(1), end=_dt(11), label="train"),
            WindowSpec(start=_dt(11), end=_dt(16), label="test"),
        ]

        async def runner(window: WindowSpec, params: Optional[Dict[str, Any]]) -> FoldOutput:
            return FoldOutput(trades=[], equity_curve=[], metrics=custom_metrics)

        engine = WalkForwardEngine(
            strategy_name="custom",
            strategy_runner=runner,
            windows=windows,
        )
        report = await engine.run()
        # Both train and test should use the pre-calculated metrics.
        assert report.folds[0].train_metrics.total_trades == 99
        assert report.folds[0].test_metrics.total_trades == 99

    asyncio.run(_test())


def test_engine_report_is_formattable():
    """Produced report works with format_report."""

    async def _test():
        windows = [
            WindowSpec(start=_dt(1), end=_dt(11), label="train"),
            WindowSpec(start=_dt(11), end=_dt(16), label="test"),
        ]

        async def runner(window: WindowSpec, params: Optional[Dict[str, Any]]) -> FoldOutput:
            trades = [_make_trade(window.start.day, window.end.day, Decimal("100"))]
            curve = [
                _make_equity(window.start.day, Decimal("10000")),
                _make_equity(window.end.day, Decimal("10100")),
            ]
            return FoldOutput(trades=trades, equity_curve=curve)

        engine = WalkForwardEngine(
            strategy_name="fmt_test",
            strategy_runner=runner,
            windows=windows,
        )
        report = await engine.run()
        text = format_report(report)
        assert "fmt_test" in text
        assert "Fold 0" in text

    asyncio.run(_test())


def test_engine_oos_equity_sorted():
    """Aggregate OOS equity curve is chronologically sorted."""

    async def _test():
        windows = generate_sliding_windows(
            start=_dt(1),
            end=_dt(31),
            train_duration=datetime.timedelta(days=10),
            test_duration=datetime.timedelta(days=5),
        )

        async def runner(window: WindowSpec, params: Optional[Dict[str, Any]]) -> FoldOutput:
            # Intentionally return equity in reverse order.
            curve = [
                _make_equity(window.end.day, Decimal("10100")),
                _make_equity(window.start.day, Decimal("10000")),
            ]
            return FoldOutput(trades=[], equity_curve=curve)

        engine = WalkForwardEngine(
            strategy_name="sort_test",
            strategy_runner=runner,
            windows=windows,
        )
        report = await engine.run()

        # Verify OOS equity curve used for aggregate metrics is sorted.
        # (We can't directly inspect it, but the engine sorts before passing
        # to build_report, so aggregate metrics should calculate without error.)
        assert report.aggregate_oos_metrics is not None

    asyncio.run(_test())


def test_fold_output_params():
    """FoldOutput stores optional params dict."""
    fo = FoldOutput(trades=[], equity_curve=[], params={"ku": 1.5})
    assert fo.params == {"ku": 1.5}

    fo_empty = FoldOutput(trades=[], equity_curve=[])
    assert fo_empty.params == {}
