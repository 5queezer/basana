from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Optional

from basana.core import enums, pair

from .signals import NormalizedSignal


@dataclass(frozen=True)
class PositionSnapshot:
    pair: pair.Pair
    position: enums.Position
    gross_exposure: Decimal
    entry_price: Decimal
    last_price: Decimal


@dataclass(frozen=True)
class RiskDecision:
    accepted: bool
    reason: str
    active_positions: int
    gross_exposure: Decimal


class PortfolioRiskManager:
    def __init__(self, max_positions: int, max_gross_exposure: Decimal):
        if max_positions <= 0:
            raise ValueError("max_positions must be > 0")
        if max_gross_exposure <= 0:
            raise ValueError("max_gross_exposure must be > 0")
        self._max_positions = max_positions
        self._max_gross_exposure = max_gross_exposure
        self._positions: Dict[pair.Pair, PositionSnapshot] = {}

    @property
    def gross_exposure(self) -> Decimal:
        return sum((position.gross_exposure for position in self._positions.values()), start=Decimal("0"))

    @property
    def active_positions(self) -> int:
        return len(self._positions)

    def get_position(self, signal_pair: pair.Pair) -> Optional[PositionSnapshot]:
        return self._positions.get(signal_pair)

    def positions(self) -> Dict[pair.Pair, PositionSnapshot]:
        return dict(self._positions)

    def mark_price(self, signal_pair: pair.Pair, price: Decimal):
        current = self._positions.get(signal_pair)
        if current is None:
            return
        self._positions[signal_pair] = PositionSnapshot(
            pair=current.pair,
            position=current.position,
            gross_exposure=current.gross_exposure,
            entry_price=current.entry_price,
            last_price=price,
        )

    def apply_signal(self, signal: NormalizedSignal, price: Decimal) -> RiskDecision:
        current = self._positions.get(signal.pair)

        if signal.position == enums.Position.NEUTRAL:
            if current is not None:
                self._positions.pop(signal.pair)
            return RiskDecision(True, "flattened", self.active_positions, self.gross_exposure)

        requested_exposure = signal.target_gross_exposure
        if requested_exposure == 0:
            return RiskDecision(False, "zero exposure request", self.active_positions, self.gross_exposure)

        replacing_existing = current is not None
        next_positions = self.active_positions + (0 if replacing_existing else 1)
        next_gross = self.gross_exposure - (current.gross_exposure if current else Decimal("0")) + requested_exposure

        if next_positions > self._max_positions:
            return RiskDecision(False, "max positions exceeded", self.active_positions, self.gross_exposure)
        if next_gross > self._max_gross_exposure:
            return RiskDecision(False, "max gross exposure exceeded", self.active_positions, self.gross_exposure)

        entry_price = current.entry_price if current and current.position == signal.position else price
        self._positions[signal.pair] = PositionSnapshot(
            pair=signal.pair,
            position=signal.position,
            gross_exposure=requested_exposure,
            entry_price=entry_price,
            last_price=price,
        )
        return RiskDecision(True, "accepted", self.active_positions, self.gross_exposure)
