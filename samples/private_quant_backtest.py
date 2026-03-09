from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import asyncio
import datetime
import logging

import basana as bs
from basana.external.binance.csv import BarSource
from basana.quant import (
    ActionTextSignalPlugin,
    PaperSimulationEngine,
    PortfolioRiskManager,
    RankedTableSignalPlugin,
    SignalSourcePluginAdapter,
)


RANKED_SIGNAL_TABLE = """
| Rank | Symbol | Score | Secondary Rank | Time |
| --- | --- | --- | --- | --- |
| 1 | BTC | 78.5 | 12 | 2021-01-02T00:00:00+00:00 |
| 2 | BTC | 82.0 | 9 | 2021-01-03T00:00:00+00:00 |
""".strip()

ACTION_TEXT_SIGNALS = """
[2021-01-04T00:00:00+00:00] SELL BTCUSDT - take profit after failed breakout
""".strip()


async def main():
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s %(levelname)s] %(message)s")

    event_dispatcher = bs.backtesting_dispatcher()
    instrument = bs.Pair("BTC", "USDT")
    sample_path = Path(__file__).parent / "data" / "quant_btcusdt_day.csv"
    default_when = datetime.datetime(2021, 1, 1, tzinfo=datetime.timezone.utc)

    ranked_plugin = RankedTableSignalPlugin.from_markdown(
        RANKED_SIGNAL_TABLE,
        default_when=default_when,
        quote_symbol="USDT",
        source="sample-ranked-table",
        top_n=3,
    )
    action_text_plugin = ActionTextSignalPlugin.from_text(
        ACTION_TEXT_SIGNALS,
        default_when=default_when,
        quote_symbol="USDT",
        source="sample-action-text",
    )

    ranked_source = SignalSourcePluginAdapter(event_dispatcher, ranked_plugin)
    action_text_source = SignalSourcePluginAdapter(event_dispatcher, action_text_plugin)
    risk_manager = PortfolioRiskManager(max_positions=1, max_gross_exposure=Decimal("1.0"))
    engine = PaperSimulationEngine(risk_manager, starting_equity=Decimal("10000"))

    bar_source = BarSource(instrument, str(sample_path), "1d")
    event_dispatcher.subscribe(bar_source, ranked_source.on_bar_event)
    event_dispatcher.subscribe(bar_source, action_text_source.on_bar_event)
    event_dispatcher.subscribe(bar_source, engine.on_bar_event)
    ranked_source.subscribe(engine.on_signal)
    action_text_source.subscribe(engine.on_signal)

    await event_dispatcher.run()

    report = engine.build_report(starting_equity=Decimal("10000"))
    logging.info(
        "simulation finished | start=%s end=%s accepted=%s rejected=%s active_positions=%s",
        report.starting_equity,
        report.ending_equity,
        report.accepted_signals,
        report.rejected_signals,
        report.active_positions,
    )


if __name__ == "__main__":
    asyncio.run(main())
