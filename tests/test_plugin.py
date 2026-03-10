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
from typing import Sequence
import asyncio
import datetime

from dateutil import tz
import pytest

import basana as bs
from basana.core.plugin import (
    DataEnvelope,
    DataKind,
    DataPlugin,
    PluginRegistry,
    SignalDirection,
    SignalEnvelope,
    SignalPlugin,
    SourceMeta,
)

utc = tz.UTC


def _dt(day=1, hour=12):
    return datetime.datetime(2026, 1, day, hour, 0, 0, tzinfo=utc)


# --- Concrete test plugin implementations ---


class MockDataPlugin(DataPlugin):
    @property
    def name(self) -> str:
        return "mock_data"

    @property
    def supported_kinds(self) -> Sequence[DataKind]:
        return [DataKind.PRICE, DataKind.INDICATOR]


class MockSignalPlugin(SignalPlugin):
    @property
    def name(self) -> str:
        return "mock_signal"

    @property
    def supported_kinds(self) -> Sequence[DataKind]:
        return [DataKind.SIGNAL]


class MockSentimentPlugin(DataPlugin):
    @property
    def name(self) -> str:
        return "mock_sentiment"

    @property
    def supported_kinds(self) -> Sequence[DataKind]:
        return [DataKind.SENTIMENT]


# --- DataEnvelope tests ---


def test_data_envelope_attributes():
    envelope = DataEnvelope(
        when=_dt(),
        kind=DataKind.PRICE,
        meta=SourceMeta(source="test"),
        pair=bs.Pair("BTC", "USD"),
        payload={"price": Decimal("50000")},
    )
    assert envelope.kind == DataKind.PRICE
    assert envelope.pair == bs.Pair("BTC", "USD")
    assert envelope.payload == {"price": Decimal("50000")}
    assert envelope.when == _dt()


def test_signal_envelope():
    envelope = SignalEnvelope(
        when=_dt(),
        kind=DataKind.SIGNAL,
        meta=SourceMeta(source="test", confidence=Decimal("0.85")),
        pair=bs.Pair("BTC", "USD"),
        direction=SignalDirection.LONG,
        strength=Decimal("0.8"),
    )
    assert envelope.direction == SignalDirection.LONG
    assert envelope.strength == Decimal("0.8")
    assert envelope.meta.confidence == Decimal("0.85")


def test_source_meta_defaults():
    meta = SourceMeta(source="test")
    assert meta.version == "1.0"
    assert meta.freshness is None
    assert meta.confidence is None


def test_source_meta_with_freshness():
    meta = SourceMeta(
        source="lunarcrush",
        version="2.0",
        freshness=datetime.timedelta(seconds=30),
        confidence=Decimal("0.9"),
    )
    assert meta.freshness == datetime.timedelta(seconds=30)


# --- Plugin base class tests ---


def test_plugin_emit_and_subscribe(backtesting_dispatcher):
    async def impl():
        plugin = MockDataPlugin(backtesting_dispatcher)
        received = []

        async def handler(envelope):
            received.append(envelope)

        plugin.subscribe(handler)

        envelope = DataEnvelope(
            when=_dt(),
            kind=DataKind.PRICE,
            meta=SourceMeta(source="test"),
            payload={"price": "50000"},
        )
        plugin.emit(envelope)
        await backtesting_dispatcher.run()

        assert len(received) == 1
        assert received[0] is envelope

    asyncio.run(impl())


def test_plugin_config(backtesting_dispatcher):
    plugin = MockDataPlugin(backtesting_dispatcher, config={"api_key": "test123"})
    assert plugin.config["api_key"] == "test123"


def test_plugin_default_config(backtesting_dispatcher):
    plugin = MockDataPlugin(backtesting_dispatcher)
    assert plugin.config == {}


def test_plugin_name(backtesting_dispatcher):
    plugin = MockDataPlugin(backtesting_dispatcher)
    assert plugin.name == "mock_data"


def test_plugin_supported_kinds(backtesting_dispatcher):
    plugin = MockDataPlugin(backtesting_dispatcher)
    assert DataKind.PRICE in plugin.supported_kinds
    assert DataKind.INDICATOR in plugin.supported_kinds


# --- PluginRegistry tests ---


def test_registry_register(backtesting_dispatcher):
    registry = PluginRegistry(backtesting_dispatcher)
    plugin = MockDataPlugin(backtesting_dispatcher)
    registry.register(plugin)
    assert "mock_data" in registry.plugins
    assert registry.get("mock_data") is plugin


def test_registry_register_duplicate(backtesting_dispatcher):
    registry = PluginRegistry(backtesting_dispatcher)
    plugin1 = MockDataPlugin(backtesting_dispatcher)
    plugin2 = MockDataPlugin(backtesting_dispatcher)
    registry.register(plugin1)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(plugin2)


def test_registry_unregister(backtesting_dispatcher):
    registry = PluginRegistry(backtesting_dispatcher)
    plugin = MockDataPlugin(backtesting_dispatcher)
    registry.register(plugin)
    registry.unregister("mock_data")
    assert "mock_data" not in registry.plugins


def test_registry_unregister_not_found(backtesting_dispatcher):
    registry = PluginRegistry(backtesting_dispatcher)
    with pytest.raises(KeyError, match="not registered"):
        registry.unregister("nonexistent")


def test_registry_get_not_found(backtesting_dispatcher):
    registry = PluginRegistry(backtesting_dispatcher)
    with pytest.raises(KeyError, match="not registered"):
        registry.get("nonexistent")


def test_registry_find_by_kind(backtesting_dispatcher):
    registry = PluginRegistry(backtesting_dispatcher)
    data_plugin = MockDataPlugin(backtesting_dispatcher)
    signal_plugin = MockSignalPlugin(backtesting_dispatcher)
    registry.register(data_plugin)
    registry.register(signal_plugin)

    price_plugins = registry.find_by_kind(DataKind.PRICE)
    assert len(price_plugins) == 1
    assert price_plugins[0] is data_plugin

    signal_plugins = registry.find_by_kind(DataKind.SIGNAL)
    assert len(signal_plugins) == 1
    assert signal_plugins[0] is signal_plugin

    sentiment_plugins = registry.find_by_kind(DataKind.SENTIMENT)
    assert len(sentiment_plugins) == 0


def test_registry_load_from_config(backtesting_dispatcher):
    registry = PluginRegistry(backtesting_dispatcher)
    configs = [
        {
            "class": "tests.test_plugin.MockDataPlugin",
            "config": {"key": "value"},
        },
        {
            "class": "tests.test_plugin.MockSignalPlugin",
        },
    ]
    loaded = registry.load_from_config(configs)
    assert len(loaded) == 2
    assert "mock_data" in registry.plugins
    assert "mock_signal" in registry.plugins
    assert registry.get("mock_data").config == {"key": "value"}
    assert registry.get("mock_signal").config == {}


def test_registry_plugins_property(backtesting_dispatcher):
    registry = PluginRegistry(backtesting_dispatcher)
    assert registry.plugins == {}
    plugin = MockDataPlugin(backtesting_dispatcher)
    registry.register(plugin)
    plugins = registry.plugins
    assert len(plugins) == 1
    # Verify it's a copy.
    plugins["fake"] = plugin  # type: ignore[assignment]
    assert "fake" not in registry.plugins


# --- DataKind and SignalDirection enum coverage ---


def test_data_kind_values():
    assert DataKind.SIGNAL.value == "signal"
    assert DataKind.PRICE.value == "price"
    assert DataKind.INDICATOR.value == "indicator"
    assert DataKind.SENTIMENT.value == "sentiment"
    assert DataKind.METADATA.value == "metadata"


def test_signal_direction_values():
    assert SignalDirection.LONG.value == "long"
    assert SignalDirection.SHORT.value == "short"
    assert SignalDirection.NEUTRAL.value == "neutral"


# --- DataEnvelope default factory ---


def test_data_envelope_default_payload():
    envelope = DataEnvelope(
        when=_dt(),
        kind=DataKind.METADATA,
        meta=SourceMeta(source="test"),
    )
    assert envelope.payload == {}
    assert envelope.pair is None
