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

"""Walk-forward evaluation engine.

Runs a user-supplied strategy factory over train/test window pairs,
collects per-fold metrics via :class:`TradingLedger`, and produces
an :class:`EvaluationReport`.

Typical usage::

    from basana.core.evaluation.engine import WalkForwardEngine

    engine = WalkForwardEngine(
        strategy_name="pid_mean_reversion",
        bar_source_factory=my_bar_source_factory,
        strategy_runner=my_strategy_runner,
        windows=generate_sliding_windows(...),
        periods_per_year=365 * 24,
    )
    report = await engine.run()
    print(format_report(report))
"""

from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence
import logging

from basana.core import logs
from basana.core.evaluation.report import build_report
from basana.core.evaluation.types import EvaluationReport, FoldResult, WindowSpec
from basana.core.evaluation.walk_forward import pair_windows
from basana.core.ledger.types import EquitySnapshot, PerformanceMetrics, TradeRecord


logger = logging.getLogger(__name__)


class FoldOutput:
    """Container returned by a strategy runner for a single window.

    :param trades: Completed trade records within the window.
    :param equity_curve: Equity snapshots within the window.
    :param metrics: Pre-calculated metrics, or ``None`` to auto-calculate.
    :param params: Optional dict of parameters used (e.g. tuned hyperparams).
    """

    def __init__(
        self,
        trades: Sequence[TradeRecord],
        equity_curve: Sequence[EquitySnapshot],
        metrics: Optional[PerformanceMetrics] = None,
        params: Optional[Dict[str, Any]] = None,
    ):
        self.trades = trades
        self.equity_curve = equity_curve
        self.metrics = metrics
        self.params = params or {}


#: Signature for a strategy runner callable.
#:
#: Given a :class:`WindowSpec` and optional params dict, it must:
#:   1. Set up a dispatcher + exchange + strategy for the window period.
#:   2. Run the backtest.
#:   3. Return a :class:`FoldOutput` with trades and equity curve.
#:
#: The ``params`` argument carries forward the best parameters found
#: during the training window when running the corresponding test window.
StrategyRunner = Callable[[WindowSpec, Optional[Dict[str, Any]]], Awaitable[FoldOutput]]

#: Signature for an optional parameter optimizer callable.
#:
#: Given training :class:`FoldOutput`, returns the best parameter dict
#: to use on the test window.  If not provided, the engine runs test
#: windows with ``params=None``.
ParamOptimizer = Callable[[WindowSpec, FoldOutput], Awaitable[Dict[str, Any]]]


class WalkForwardEngine:
    """Runs walk-forward evaluation across train/test window pairs.

    :param strategy_name: Name for the evaluation report.
    :param strategy_runner: Async callable that runs a single window.
    :param windows: Flat list of alternating train/test :class:`WindowSpec`.
        Use :func:`generate_sliding_windows` or :func:`generate_expanding_windows`.
    :param param_optimizer: Optional async callable that extracts best params
        from a training fold.  If provided, its output is passed to the test runner.
    :param periods_per_year: Annualization factor for aggregate metrics.
    """

    def __init__(
        self,
        strategy_name: str,
        strategy_runner: StrategyRunner,
        windows: Sequence[WindowSpec],
        param_optimizer: Optional[ParamOptimizer] = None,
        periods_per_year: int = 252,
    ):
        self._strategy_name = strategy_name
        self._runner = strategy_runner
        self._folds = pair_windows(list(windows))
        self._optimizer = param_optimizer
        self._periods_per_year = periods_per_year

    async def run(self) -> EvaluationReport:
        """Execute the walk-forward evaluation.

        For each fold:
          1. Run the strategy on the training window.
          2. If a ``param_optimizer`` is set, extract best params from training.
          3. Run the strategy on the test window (with optimized params if available).
          4. Collect :class:`FoldResult`.

        :returns: An :class:`EvaluationReport` with per-fold and aggregate OOS metrics.
        """
        from basana.core.ledger.metrics import calculate_metrics

        fold_results: List[FoldResult] = []
        all_oos_trades: List[TradeRecord] = []
        all_oos_equity: List[EquitySnapshot] = []

        for i, (train_window, test_window) in enumerate(self._folds):
            logger.info(
                logs.StructuredMessage(
                    "Running fold",
                    fold=i,
                    train=f"{train_window.start.date()} → {train_window.end.date()}",
                    test=f"{test_window.start.date()} → {test_window.end.date()}",
                )
            )

            # 1. Train
            train_output = await self._runner(train_window, None)
            train_metrics = train_output.metrics or calculate_metrics(
                train_output.trades, train_output.equity_curve, self._periods_per_year
            )

            # 2. Optimize params (optional)
            test_params: Optional[Dict[str, Any]] = None
            if self._optimizer is not None:
                test_params = await self._optimizer(train_window, train_output)
                logger.info(
                    logs.StructuredMessage(
                        "Optimized params for test",
                        fold=i,
                        params=str(test_params),
                    )
                )

            # 3. Test
            test_output = await self._runner(test_window, test_params)
            test_metrics = test_output.metrics or calculate_metrics(
                test_output.trades, test_output.equity_curve, self._periods_per_year
            )

            fold_results.append(FoldResult(
                fold_index=i,
                train_window=train_window,
                test_window=test_window,
                train_metrics=train_metrics,
                test_metrics=test_metrics,
            ))

            all_oos_trades.extend(test_output.trades)
            all_oos_equity.extend(test_output.equity_curve)

            logger.info(
                logs.StructuredMessage(
                    "Fold complete",
                    fold=i,
                    train_trades=train_metrics.total_trades,
                    test_trades=test_metrics.total_trades,
                    test_pnl=str(test_metrics.total_pnl),
                )
            )

        # Sort OOS equity curve chronologically for aggregate metrics.
        all_oos_equity.sort(key=lambda s: s.when)

        return build_report(
            self._strategy_name,
            fold_results,
            all_oos_trades,
            all_oos_equity,
            self._periods_per_year,
        )
