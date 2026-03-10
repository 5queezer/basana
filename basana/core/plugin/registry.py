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

from typing import Any, Dict, List, Sequence, Type
import importlib
import logging

from basana.core import dispatcher
from basana.core.plugin.base import Plugin
from basana.core.plugin.types import DataKind


logger = logging.getLogger(__name__)


class PluginRegistry:
    """Registry for managing plugin instances.

    Provides plugin discovery, registration, and config-driven loading.

    :param event_dispatcher: The event dispatcher for plugin initialization.
    """

    def __init__(self, event_dispatcher: dispatcher.EventDispatcher):
        self._dispatcher = event_dispatcher
        self._plugins: Dict[str, Plugin] = {}

    def register(self, plugin: Plugin) -> None:
        """Register a plugin instance.

        :param plugin: The plugin to register.
        :raises ValueError: If a plugin with the same name is already registered.
        """
        if plugin.name in self._plugins:
            raise ValueError(f"Plugin '{plugin.name}' is already registered")
        self._plugins[plugin.name] = plugin
        logger.info(f"Plugin registered: {plugin.name}")

    def unregister(self, name: str) -> None:
        """Unregister a plugin by name.

        :param name: The plugin name to unregister.
        :raises KeyError: If no plugin with that name is registered.
        """
        if name not in self._plugins:
            raise KeyError(f"Plugin '{name}' is not registered")
        del self._plugins[name]
        logger.info(f"Plugin unregistered: {name}")

    def get(self, name: str) -> Plugin:
        """Get a registered plugin by name.

        :param name: The plugin name.
        :returns: The plugin instance.
        :raises KeyError: If no plugin with that name is registered.
        """
        if name not in self._plugins:
            raise KeyError(f"Plugin '{name}' is not registered")
        return self._plugins[name]

    @property
    def plugins(self) -> Dict[str, Plugin]:
        """All registered plugins."""
        return dict(self._plugins)

    def find_by_kind(self, kind: DataKind) -> List[Plugin]:
        """Find all plugins that support a given data kind.

        :param kind: The data kind to search for.
        :returns: List of plugins that support the given kind.
        """
        return [p for p in self._plugins.values() if kind in p.supported_kinds]

    def load_from_config(self, plugin_configs: Sequence[Dict[str, Any]]) -> List[Plugin]:
        """Load and register plugins from configuration dictionaries.

        Each config dict must have a ``class`` key with the fully qualified class name
        (e.g. ``"basana.external.binance.plugin.BinanceDataPlugin"``), and optionally
        a ``config`` key with plugin-specific configuration.

        :param plugin_configs: List of plugin configuration dictionaries.
        :returns: List of loaded plugin instances.
        """
        loaded: List[Plugin] = []
        for plugin_config in plugin_configs:
            class_path = plugin_config["class"]
            config = plugin_config.get("config", {})
            plugin = self._instantiate(class_path, config)
            self.register(plugin)
            loaded.append(plugin)
        return loaded

    def _instantiate(self, class_path: str, config: Dict[str, Any]) -> Plugin:
        """Instantiate a plugin from its class path.

        :param class_path: Fully qualified class name.
        :param config: Plugin configuration.
        :returns: The instantiated plugin.
        """
        module_path, class_name = class_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        plugin_class: Type[Plugin] = getattr(module, class_name)
        return plugin_class(self._dispatcher, config)
