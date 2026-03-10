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

from typing import List, Optional
import datetime
import logging

from basana.core import dt
from basana.core.evaluation.types import WindowSpec


logger = logging.getLogger(__name__)


def generate_expanding_windows(
    start: datetime.datetime,
    end: datetime.datetime,
    test_duration: datetime.timedelta,
    min_train_duration: datetime.timedelta,
    step: Optional[datetime.timedelta] = None,
) -> List[WindowSpec]:
    """Generate expanding (anchored) training windows with fixed-size test windows.

    The training window starts at ``start`` and grows with each fold. The test window
    follows immediately after and has a fixed duration.

    :param start: Start of the first training window (timezone-aware).
    :param end: End of the evaluation period (timezone-aware).
    :param test_duration: Duration of each test window.
    :param min_train_duration: Minimum training window duration.
    :param step: Step size between folds. Defaults to ``test_duration``.
    :returns: List of alternating train/test WindowSpec pairs.
    """
    assert not dt.is_naive(start), f"{start} should have timezone information set"
    assert not dt.is_naive(end), f"{end} should have timezone information set"
    assert test_duration.total_seconds() > 0, "test_duration must be positive"
    assert min_train_duration.total_seconds() > 0, "min_train_duration must be positive"

    if step is None:
        step = test_duration

    windows: List[WindowSpec] = []
    train_end = start + min_train_duration

    while train_end + test_duration <= end:
        windows.append(WindowSpec(start=start, end=train_end, label="train"))
        windows.append(WindowSpec(start=train_end, end=train_end + test_duration, label="test"))
        train_end += step

    return windows


def generate_sliding_windows(
    start: datetime.datetime,
    end: datetime.datetime,
    train_duration: datetime.timedelta,
    test_duration: datetime.timedelta,
    step: Optional[datetime.timedelta] = None,
) -> List[WindowSpec]:
    """Generate sliding (rolling) windows with fixed train and test durations.

    Both training and test windows have fixed durations and slide forward.

    :param start: Start of the first training window (timezone-aware).
    :param end: End of the evaluation period (timezone-aware).
    :param train_duration: Duration of each training window.
    :param test_duration: Duration of each test window.
    :param step: Step size between folds. Defaults to ``test_duration``.
    :returns: List of alternating train/test WindowSpec pairs.
    """
    assert not dt.is_naive(start), f"{start} should have timezone information set"
    assert not dt.is_naive(end), f"{end} should have timezone information set"
    assert train_duration.total_seconds() > 0, "train_duration must be positive"
    assert test_duration.total_seconds() > 0, "test_duration must be positive"

    if step is None:
        step = test_duration

    windows: List[WindowSpec] = []
    train_start = start

    while train_start + train_duration + test_duration <= end:
        train_end = train_start + train_duration
        windows.append(WindowSpec(start=train_start, end=train_end, label="train"))
        windows.append(WindowSpec(start=train_end, end=train_end + test_duration, label="test"))
        train_start += step

    return windows


def pair_windows(windows: List[WindowSpec]) -> List[tuple]:
    """Pair alternating train/test windows into (train, test) tuples.

    :param windows: List of alternating train/test WindowSpec instances.
    :returns: List of (train_window, test_window) tuples.
    """
    pairs = []
    for i in range(0, len(windows) - 1, 2):
        pairs.append((windows[i], windows[i + 1]))
    return pairs
