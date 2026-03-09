from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Tuple

from basana.core import bar, enums, pair

from .portfolio import PortfolioRiskManager
from .signals import NormalizedSignal


@dataclass(frozen=True)
class SimulationReport:
    starting_equity: Decimal
    ending_equity: Decimal
    accepted_signals: int
    rejected_signals: int
    active_positions: int


class PaperSimulationEngine:
    def __init__(self, risk_manager: PortfolioRiskManager, starting_equity: Decimal):
        self._risk_manager = risk_manager
        self._equity = starting_equity
        self._last_prices: Dict[pair.Pair, Decimal] = {}
        self._accepted_signals = 0
        self._rejected_signals = 0

    @property
    def equity(self) -> Decimal:
        return self._equity

    async def on_bar_event(self, bar_event: bar.BarEvent):
        instrument = bar_event.bar.pair
        close = bar_event.bar.close
        previous = self._last_prices.get(instrument)
        position = self._risk_manager.get_position(instrument)
        if previous is not None and position is not None and previous != 0:
            direction = Decimal("1") if position.position == enums.Position.LONG else Decimal("-1")
            change = (close - previous) / previous
            pnl = self._equity * position.gross_exposure * direction * change
            self._equity += pnl
        self._last_prices[instrument] = close
        self._risk_manager.mark_price(instrument, close)

    async def on_signal(self, signal: NormalizedSignal):
        price = self._last_prices.get(signal.pair)
        if price is None:
            self._rejected_signals += 1
            return
        decision = self._risk_manager.apply_signal(signal, price)
        if decision.accepted:
            self._accepted_signals += 1
        else:
            self._rejected_signals += 1

    def build_report(self, starting_equity: Decimal) -> SimulationReport:
        return SimulationReport(
            starting_equity=starting_equity,
            ending_equity=self._equity,
            accepted_signals=self._accepted_signals,
            rejected_signals=self._rejected_signals,
            active_positions=self._risk_manager.active_positions,
        )
