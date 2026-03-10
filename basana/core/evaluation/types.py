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

from typing import Optional, Sequence
import dataclasses
import datetime

from basana.core.ledger.types import PerformanceMetrics


@dataclasses.dataclass(frozen=True)
class WindowSpec:
    """Specification for an evaluation window.

    :param start: Window start datetime (timezone-aware).
    :param end: Window end datetime (timezone-aware).
    :param label: Optional label (e.g. "train", "test", "oos").
    """

    start: datetime.datetime
    end: datetime.datetime
    label: Optional[str] = None


@dataclasses.dataclass(frozen=True)
class FoldResult:
    """Result of evaluating a strategy over a single fold/window.

    :param fold_index: Zero-based fold index.
    :param train_window: The training window spec.
    :param test_window: The test (out-of-sample) window spec.
    :param train_metrics: Performance metrics on training data.
    :param test_metrics: Performance metrics on test (out-of-sample) data.
    """

    fold_index: int
    train_window: WindowSpec
    test_window: WindowSpec
    train_metrics: PerformanceMetrics
    test_metrics: PerformanceMetrics


@dataclasses.dataclass(frozen=True)
class EvaluationReport:
    """Summary report from a walk-forward or rolling evaluation.

    :param strategy_name: Name of the strategy being evaluated.
    :param folds: Results for each fold.
    :param aggregate_oos_metrics: Aggregated out-of-sample metrics across all folds.
    """

    strategy_name: str
    folds: Sequence[FoldResult]
    aggregate_oos_metrics: PerformanceMetrics
