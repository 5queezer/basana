from decimal import Decimal
import asyncio

import basana as bs
from basana.external.binance.csv import BarSource
from basana.quant import (
    NormalizedSignal,
    PaperSimulationEngine,
    PortfolioRiskManager,
    SignalSourcePlugin,
    SignalSourcePluginAdapter,
)


class LongOnFirstReadyPlugin(SignalSourcePlugin):
    def __init__(self, signal_pair: bs.Pair):
        self._pair = signal_pair
        self._sent = False

    async def on_bar(self, bar_event: bs.BarEvent):
        if self._sent:
            return []
        self._sent = True
        return [
            NormalizedSignal(
                when=bar_event.when,
                pair=self._pair,
                position=bs.Position.LONG,
                source="test-plugin",
                target_gross_exposure=Decimal("1.0"),
            )
        ]


def test_paper_simulation_engine_runs_end_to_end(backtesting_dispatcher):
    async def impl():
        pair = bs.Pair("BTC", "USDT")
        bar_source = BarSource(pair, "samples/data/quant_btcusdt_day.csv", "1d")
        plugin = SignalSourcePluginAdapter(backtesting_dispatcher, LongOnFirstReadyPlugin(pair))
        risk_manager = PortfolioRiskManager(max_positions=1, max_gross_exposure=Decimal("1.0"))
        engine = PaperSimulationEngine(risk_manager, starting_equity=Decimal("10000"))

        backtesting_dispatcher.subscribe(bar_source, plugin.on_bar_event)
        backtesting_dispatcher.subscribe(bar_source, engine.on_bar_event)
        plugin.subscribe(engine.on_signal)

        await backtesting_dispatcher.run()
        report = engine.build_report(Decimal("10000"))
        assert report.accepted_signals == 1
        assert report.ending_equity > report.starting_equity

    asyncio.run(impl())
