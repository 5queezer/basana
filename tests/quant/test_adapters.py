from decimal import Decimal
from pathlib import Path
import asyncio
import datetime

import basana as bs
from basana.quant import (
    ActionTextSignalPlugin,
    RankedTableSignalPlugin,
    parse_action_text_signals,
    parse_ranked_table_signals,
)


def _fixture_path(name: str) -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "quant" / name


def test_parse_ranked_table_signals():
    signals = parse_ranked_table_signals(
        _fixture_path("ranked_table_signals.md").read_text(),
        default_when=datetime.datetime(2021, 1, 1, tzinfo=datetime.timezone.utc),
        top_n=2,
        source="fixture-ranked",
    )

    assert len(signals) == 2
    assert signals[0].pair == bs.Pair("BTC", "USDT")
    assert signals[0].position == bs.Position.LONG
    assert signals[0].strength == Decimal("0.785")
    assert signals[0].target_gross_exposure == Decimal("1.000")
    assert signals[0].metadata["rank"] == 1
    assert signals[0].metadata["score"] == "78.5"
    assert signals[1].pair == bs.Pair("ETH", "USDT")
    assert signals[1].target_gross_exposure == Decimal("0.500")


def test_parse_action_text_signals():
    signals = parse_action_text_signals(
        _fixture_path("action_text_signals.txt").read_text(),
        default_when=datetime.datetime(2021, 1, 1, tzinfo=datetime.timezone.utc),
        source="fixture-actions",
    )

    assert len(signals) == 3
    assert signals[0].pair == bs.Pair("BTC", "USDT")
    assert signals[0].position == bs.Position.LONG
    assert signals[0].metadata["trigger_price"] == "102"
    assert signals[1].pair == bs.Pair("ETH", "USDT")
    assert signals[1].position == bs.Position.SHORT
    assert signals[2].position == bs.Position.NEUTRAL
    assert signals[2].target_gross_exposure == Decimal("0")


def _build_bar_event(when: datetime.datetime, instrument: bs.Pair) -> bs.BarEvent:
    return bs.BarEvent(
        when,
        bs.Bar(
            when,
            instrument,
            Decimal("1"),
            Decimal("1"),
            Decimal("1"),
            Decimal("1"),
            Decimal("1"),
        ),
    )


def test_ranked_table_plugin_emits_only_due_signals():
    plugin = RankedTableSignalPlugin.from_markdown(
        _fixture_path("ranked_table_signals.md").read_text(),
        default_when=datetime.datetime(2021, 1, 1, tzinfo=datetime.timezone.utc),
        top_n=2,
        source="fixture-ranked",
    )
    instrument = bs.Pair("BTC", "USDT")
    due = asyncio.run(plugin.on_bar(_build_bar_event(
        datetime.datetime(2021, 1, 2, tzinfo=datetime.timezone.utc),
        instrument,
    )))
    not_due = asyncio.run(plugin.on_bar(_build_bar_event(
        datetime.datetime(2021, 1, 3, tzinfo=datetime.timezone.utc),
        instrument,
    )))

    assert len(due) == 1
    assert due[0].pair == instrument
    assert not not_due


def test_action_text_plugin_emits_matching_pair_only_once():
    plugin = ActionTextSignalPlugin.from_text(
        _fixture_path("action_text_signals.txt").read_text(),
        default_when=datetime.datetime(2021, 1, 1, tzinfo=datetime.timezone.utc),
        source="fixture-actions",
    )
    instrument = bs.Pair("BTC", "USDT")
    first = asyncio.run(plugin.on_bar(_build_bar_event(
        datetime.datetime(2021, 1, 2, tzinfo=datetime.timezone.utc),
        instrument,
    )))
    second = asyncio.run(plugin.on_bar(_build_bar_event(
        datetime.datetime(2021, 1, 4, tzinfo=datetime.timezone.utc),
        instrument,
    )))

    assert [signal.position for signal in first] == [bs.Position.LONG]
    assert [signal.position for signal in second] == [bs.Position.NEUTRAL]
