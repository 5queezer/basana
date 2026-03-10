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
from typing import Any, Dict, Optional
import dataclasses
import datetime
import enum

from basana.core import event
from basana.core.pair import Pair


class SignalDirection(enum.Enum):
    """Direction of a trading signal."""

    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"


class DataKind(enum.Enum):
    """Kind of data provided by a plugin."""

    SIGNAL = "signal"
    PRICE = "price"
    INDICATOR = "indicator"
    SENTIMENT = "sentiment"
    METADATA = "metadata"


@dataclasses.dataclass(frozen=True)
class SourceMeta:
    """Metadata about the origin and quality of a data envelope.

    :param source: Name of the data source (e.g. "lunarcrush", "100eyes", "binance").
    :param version: Version of the source adapter.
    :param freshness: How old the data is at delivery time.
    :param confidence: Confidence score (0-1) if applicable.
    """

    source: str
    version: str = "1.0"
    freshness: Optional[datetime.timedelta] = None
    confidence: Optional[Decimal] = None


class DataEnvelope(event.Event):
    """Standardized wrapper for any data flowing through the plugin system.

    :param when: Timestamp of the data (timezone-aware).
    :param kind: The kind of data (signal, price, indicator, etc.).
    :param meta: Source metadata.
    :param pair: Optional trading pair this data relates to.
    :param payload: The actual data content.
    """

    def __init__(
        self,
        when: datetime.datetime,
        kind: DataKind,
        meta: SourceMeta,
        pair: Optional[Pair] = None,
        payload: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(when)
        self.kind = kind
        self.meta = meta
        self.pair = pair
        self.payload = payload if payload is not None else {}


class SignalEnvelope(DataEnvelope):
    """Standardized trading signal envelope.

    :param direction: The signal direction (long/short/neutral).
    :param strength: Signal strength (0-1).
    """

    def __init__(
        self,
        when: datetime.datetime,
        kind: DataKind,
        meta: SourceMeta,
        pair: Optional[Pair] = None,
        payload: Optional[Dict[str, Any]] = None,
        direction: SignalDirection = SignalDirection.NEUTRAL,
        strength: Decimal = Decimal(0),
    ):
        super().__init__(when, kind, meta, pair, payload)
        self.direction = direction
        self.strength = strength
