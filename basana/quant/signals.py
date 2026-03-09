from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, Sequence
import abc
import datetime

from basana.core import bar, dispatcher, enums, event, pair


@dataclass
class NormalizedSignal(event.Event):
    when: datetime.datetime
    pair: pair.Pair
    position: enums.Position
    source: str
    strength: Decimal = Decimal("1")
    target_gross_exposure: Decimal = Decimal("1")
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        event.Event.__init__(self, self.when)
        if self.strength < 0:
            raise ValueError("strength must be >= 0")
        if self.target_gross_exposure < 0:
            raise ValueError("target_gross_exposure must be >= 0")


class SignalSourcePlugin(abc.ABC):
    @abc.abstractmethod
    async def on_bar(self, bar_event: bar.BarEvent) -> Sequence[NormalizedSignal]:
        raise NotImplementedError()


class SignalSourcePluginAdapter(event.FifoQueueEventSource):
    def __init__(self, event_dispatcher: dispatcher.EventDispatcher, plugin: SignalSourcePlugin):
        super().__init__()
        self._dispatcher = event_dispatcher
        self._plugin = plugin

    async def on_bar_event(self, bar_event: bar.BarEvent):
        for signal in await self._plugin.on_bar(bar_event):
            self.push(signal)

    def subscribe(self, event_handler):
        self._dispatcher.subscribe(self, event_handler)
