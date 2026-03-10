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

from typing import Any, Awaitable, Callable, Dict, Optional, Sequence
import abc
import logging

from basana.core import dispatcher, event
from basana.core.plugin.types import DataEnvelope, DataKind


logger = logging.getLogger(__name__)


class Plugin(event.FifoQueueEventSource, event.Producer, metaclass=abc.ABCMeta):
    """Base class for all plugins (data sources, signal providers, connectors).

    A plugin is an event source that emits :class:`DataEnvelope` events. It has a lifecycle
    managed by the event dispatcher: ``initialize`` -> ``main`` -> ``finalize``.

    Subclasses must implement :meth:`name` and :meth:`supported_kinds`.

    :param event_dispatcher: The event dispatcher to register with.
    :param config: Optional configuration dictionary.
    """

    def __init__(
        self,
        event_dispatcher: dispatcher.EventDispatcher,
        config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(producer=self)
        self._dispatcher = event_dispatcher
        self._config = config or {}

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """The unique name of this plugin."""
        raise NotImplementedError()

    @property
    @abc.abstractmethod
    def supported_kinds(self) -> Sequence[DataKind]:
        """The kinds of data this plugin can provide."""
        raise NotImplementedError()

    @property
    def config(self) -> Dict[str, Any]:
        """The plugin configuration."""
        return self._config

    def emit(self, envelope: DataEnvelope) -> None:
        """Emit a data envelope as an event.

        :param envelope: The data envelope to emit.
        """
        self.push(envelope)

    def subscribe(
        self,
        handler: Callable[[DataEnvelope], Awaitable[Any]],
    ) -> None:
        """Register a handler for data envelopes emitted by this plugin.

        :param handler: Async callable that receives data envelopes.
        """
        self._dispatcher.subscribe(self, handler)  # type: ignore[arg-type]


class DataPlugin(Plugin):
    """A plugin that provides market data (prices, indicators, etc.).

    Subclasses should override :meth:`main` to produce data envelopes.
    """

    pass


class SignalPlugin(Plugin):
    """A plugin that provides trading signals.

    Subclasses should override :meth:`main` to produce signal envelopes.
    """

    pass


class ExecutionPlugin(Plugin):
    """A plugin that provides order execution capabilities.

    Subclasses should override :meth:`main` and provide execution methods.
    """

    pass
