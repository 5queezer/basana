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
from typing import Any, Iterable, List, Optional, Sequence
import math

from basana.core.ledger.types import EquitySnapshot, PerformanceMetrics, TradeRecord

_ZERO = Decimal(0)


def calculate_max_drawdown(equity_curve: Sequence[EquitySnapshot]) -> Decimal:
    """Calculate maximum drawdown from an equity curve.

    :param equity_curve: Chronologically ordered equity snapshots.
    :returns: Maximum drawdown as a positive fraction (e.g. 0.20 = 20% drawdown).
    """
    if len(equity_curve) < 2:
        return _ZERO

    peak = equity_curve[0].equity
    max_dd = _ZERO

    for snap in equity_curve[1:]:
        if snap.equity > peak:
            peak = snap.equity
        if peak > 0:
            dd = (peak - snap.equity) / peak
            if dd > max_dd:
                max_dd = dd

    return max_dd


def calculate_sharpe_ratio(
    equity_curve: Sequence[EquitySnapshot],
    risk_free_rate: Decimal = _ZERO,
    periods_per_year: int = 252,
) -> Optional[Decimal]:
    """Calculate annualized Sharpe ratio from equity curve returns.

    :param equity_curve: Chronologically ordered equity snapshots.
    :param risk_free_rate: Annualized risk-free rate as a decimal.
    :param periods_per_year: Number of periods per year for annualization.
    :returns: Annualized Sharpe ratio, or None if insufficient data.
    """
    returns = _calculate_returns(equity_curve)
    if len(returns) < 2:
        return None

    n = Decimal(len(returns))
    avg_return = _sum(returns) / n
    period_rf = risk_free_rate / Decimal(periods_per_year)
    excess_returns = [r - period_rf for r in returns]
    avg_excess = _sum(excess_returns) / n

    variance = _sum((r - avg_return) ** 2 for r in returns) / (n - Decimal(1))
    std_dev = Decimal(str(math.sqrt(float(variance))))

    if std_dev == _ZERO:
        return None

    return (avg_excess / std_dev) * Decimal(str(math.sqrt(periods_per_year)))


def calculate_sortino_ratio(
    equity_curve: Sequence[EquitySnapshot],
    risk_free_rate: Decimal = _ZERO,
    periods_per_year: int = 252,
) -> Optional[Decimal]:
    """Calculate annualized Sortino ratio from equity curve returns.

    :param equity_curve: Chronologically ordered equity snapshots.
    :param risk_free_rate: Annualized risk-free rate as a decimal.
    :param periods_per_year: Number of periods per year for annualization.
    :returns: Annualized Sortino ratio, or None if insufficient data.
    """
    returns = _calculate_returns(equity_curve)
    if len(returns) < 2:
        return None

    n = Decimal(len(returns))
    period_rf = risk_free_rate / Decimal(periods_per_year)
    excess_returns = [r - period_rf for r in returns]
    avg_excess = _sum(excess_returns) / n

    downside = [r for r in returns if r < 0]
    if not downside:
        return None

    downside_variance = _sum(r ** 2 for r in downside) / n
    downside_dev = Decimal(str(math.sqrt(float(downside_variance))))

    if downside_dev == _ZERO:
        return None

    return (avg_excess / downside_dev) * Decimal(str(math.sqrt(periods_per_year)))


def calculate_metrics(
    trades: Sequence[TradeRecord],
    equity_curve: Sequence[EquitySnapshot],
    periods_per_year: int = 252,
) -> PerformanceMetrics:
    """Calculate comprehensive performance metrics.

    :param trades: List of completed trade records.
    :param equity_curve: Chronologically ordered equity snapshots.
    :param periods_per_year: Number of periods per year for annualization.
    :returns: A :class:`PerformanceMetrics` instance.
    """
    total_trades = len(trades)
    if total_trades == 0:
        return PerformanceMetrics(
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate=_ZERO,
            total_pnl=_ZERO,
            avg_pnl=_ZERO,
            profit_factor=None,
            expectancy=_ZERO,
            max_drawdown=_ZERO,
            sharpe_ratio=None,
            sortino_ratio=None,
            calmar_ratio=None,
            avg_win=_ZERO,
            avg_loss=_ZERO,
        )

    winners = [t for t in trades if t.realized_pnl > 0]
    losers = [t for t in trades if t.realized_pnl < 0]
    winning_trades = len(winners)
    losing_trades = len(losers)

    total_pnl = _sum(t.realized_pnl for t in trades)
    avg_pnl = total_pnl / Decimal(total_trades)
    win_rate = Decimal(winning_trades) / Decimal(total_trades)

    gross_profit = _sum(t.realized_pnl for t in winners)
    gross_loss = abs(_sum(t.realized_pnl for t in losers))

    profit_factor: Optional[Decimal] = None
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss

    avg_win = gross_profit / Decimal(winning_trades) if winning_trades > 0 else _ZERO
    avg_loss = gross_loss / Decimal(losing_trades) if losing_trades > 0 else _ZERO
    loss_rate = Decimal(1) - win_rate
    expectancy = avg_win * win_rate - avg_loss * loss_rate

    max_dd = calculate_max_drawdown(equity_curve)
    sharpe = calculate_sharpe_ratio(equity_curve, periods_per_year=periods_per_year)
    sortino = calculate_sortino_ratio(equity_curve, periods_per_year=periods_per_year)

    calmar: Optional[Decimal] = None
    if max_dd > 0 and len(equity_curve) >= 2:
        total_return = (equity_curve[-1].equity - equity_curve[0].equity) / equity_curve[0].equity
        n_periods = Decimal(len(equity_curve) - 1)
        if n_periods > 0:
            annualized_return = total_return * Decimal(periods_per_year) / n_periods
            calmar = annualized_return / max_dd

    return PerformanceMetrics(
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate=win_rate,
        total_pnl=total_pnl,
        avg_pnl=avg_pnl,
        profit_factor=profit_factor,
        expectancy=expectancy,
        max_drawdown=max_dd,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        calmar_ratio=calmar,
        avg_win=avg_win,
        avg_loss=avg_loss,
    )


def _sum(values: Iterable[Any]) -> Decimal:
    """Sum Decimal values with Decimal(0) as start to avoid int return type."""
    return sum(values, _ZERO)


def _calculate_returns(equity_curve: Sequence[EquitySnapshot]) -> List[Decimal]:
    """Calculate period-over-period returns from an equity curve."""
    returns: List[Decimal] = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1].equity
        if prev != 0:
            returns.append((equity_curve[i].equity - prev) / prev)
    return returns
