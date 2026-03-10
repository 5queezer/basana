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
from typing import Optional, Sequence

from basana.core.evaluation.types import EvaluationReport, FoldResult
from basana.core.ledger.types import PerformanceMetrics, TradeRecord, EquitySnapshot
from basana.core.ledger.metrics import calculate_metrics

_ZERO = Decimal(0)


def build_report(
    strategy_name: str,
    folds: Sequence[FoldResult],
    oos_trades: Sequence[TradeRecord],
    oos_equity_curve: Sequence[EquitySnapshot],
    periods_per_year: int = 252,
) -> EvaluationReport:
    """Build an evaluation report from fold results and aggregated OOS data.

    :param strategy_name: Name of the strategy.
    :param folds: Results for each fold.
    :param oos_trades: All out-of-sample trades concatenated.
    :param oos_equity_curve: Out-of-sample equity curve.
    :param periods_per_year: Periods per year for annualization.
    :returns: An :class:`EvaluationReport`.
    """
    aggregate = calculate_metrics(oos_trades, oos_equity_curve, periods_per_year)
    return EvaluationReport(
        strategy_name=strategy_name,
        folds=folds,
        aggregate_oos_metrics=aggregate,
    )


def format_report(report: EvaluationReport) -> str:
    """Format an evaluation report as a human-readable string.

    :param report: The evaluation report.
    :returns: Formatted report string.
    """
    lines = [
        f"Strategy: {report.strategy_name}",
        f"Folds: {len(report.folds)}",
        "",
        "--- Aggregate OOS Metrics ---",
    ]
    lines.extend(_format_metrics(report.aggregate_oos_metrics))
    lines.append("")

    for fold in report.folds:
        lines.append(f"--- Fold {fold.fold_index} ---")
        lines.append(f"  Train: {fold.train_window.start} -> {fold.train_window.end}")
        lines.append(f"  Test:  {fold.test_window.start} -> {fold.test_window.end}")
        lines.append("  Train metrics:")
        lines.extend(f"    {line}" for line in _format_metrics(fold.train_metrics))
        lines.append("  Test metrics:")
        lines.extend(f"    {line}" for line in _format_metrics(fold.test_metrics))
        lines.append("")

    return "\n".join(lines)


def _format_metrics(m: PerformanceMetrics) -> list:
    lines = [
        f"Trades: {m.total_trades} (W:{m.winning_trades} L:{m.losing_trades})",
        f"Win rate: {_pct(m.win_rate)}",
        f"Total PnL: {m.total_pnl}",
        f"Avg PnL: {m.avg_pnl:.2f}",
        f"Profit factor: {m.profit_factor if m.profit_factor is not None else 'N/A'}",
        f"Expectancy: {m.expectancy:.2f}",
        f"Max drawdown: {_pct(m.max_drawdown)}",
        f"Sharpe: {_opt(m.sharpe_ratio)}",
        f"Sortino: {_opt(m.sortino_ratio)}",
        f"Calmar: {_opt(m.calmar_ratio)}",
    ]
    return lines


def _pct(value: Decimal) -> str:
    return f"{value * 100:.2f}%"


def _opt(value: Optional[Decimal]) -> str:
    if value is None:
        return "N/A"
    return f"{value:.4f}"
