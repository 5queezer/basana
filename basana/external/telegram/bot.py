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

from typing import Optional
import logging

from telegram.ext import Application, CallbackQueryHandler, CommandHandler

from basana.core import dispatcher, event
from basana.core.risk.manager import RiskManager
from basana.external.telegram.auth import UserAuthenticator, require_auth
from basana.external.telegram.config import TelegramConfig, Verbosity
from basana.external.telegram.formatters import format_fill_notification, format_signal_notification
from basana.external.telegram.handlers import (
    KEY_EVENT_DISPATCHER,
    KEY_RISK_MANAGER,
    callback_handler,
    cmd_kill_switch,
    cmd_mode,
    cmd_positions,
    cmd_risk,
    cmd_status,
)
from basana.external.telegram.rate_limit import UserRateLimiter


logger = logging.getLogger(__name__)


class TelegramBot(event.FifoQueueEventSource, event.Producer):
    """Telegram bot for monitoring and controlling basana trading strategies.

    Integrates with the event dispatcher as both an EventSource and Producer,
    observing all events via subscribe_all and providing interactive Telegram commands.

    :param config: Telegram bot configuration.
    :param event_dispatcher: The event dispatcher to integrate with.
    :param risk_manager: Optional risk manager for status queries and control.
    """

    def __init__(
        self,
        config: TelegramConfig,
        event_dispatcher: dispatcher.EventDispatcher,
        risk_manager: Optional[RiskManager] = None,
    ):
        super().__init__(producer=self)
        self._config = config
        self._dispatcher = event_dispatcher
        self._risk_manager = risk_manager
        self._authenticator = UserAuthenticator(set(config.authorized_user_ids))
        self._rate_limiter = UserRateLimiter(config.rate_limit_messages_per_minute)
        self._app: Optional[Application] = None

        # Register with the dispatcher so our producer lifecycle is managed.
        event_dispatcher.subscribe(self, self._on_own_event)  # type: ignore[arg-type]
        # Sniff all events for notifications.
        event_dispatcher.subscribe_all(self._on_event)

    async def _on_own_event(self, event: event.Event) -> None:  # pragma: no cover
        """Dummy handler for self-subscription (ensures producer registration)."""
        pass

    async def _on_event(self, evt: event.Event) -> None:
        """Observe all dispatched events and send notifications based on verbosity."""
        if self._app is None:
            return

        # Import here to avoid circular imports and allow use without telegram installed.
        from basana.core import bar
        from basana.core.event_sources.trading_signal import BaseTradingSignal

        if isinstance(evt, BaseTradingSignal) and self._config.notify_on_signal:
            if self._config.verbosity in (Verbosity.NORMAL, Verbosity.VERBOSE):
                for pair, position in evt.get_pairs():
                    text = format_signal_notification(pair, position.value, evt.when)
                    await self._send_to_all(text)

        elif isinstance(evt, bar.BarEvent) and self._config.verbosity == Verbosity.VERBOSE:
            # Only in verbose mode — very noisy.
            text = (
                f"<b>Bar: {evt.bar.pair}</b>\n"
                f"Close: <code>{evt.bar.close}</code>\n"
                f"Volume: <code>{evt.bar.volume}</code>"
            )
            await self._send_to_all(text)

    async def send_fill_notification(
        self, pair, signed_qty, fill_price, when
    ) -> None:
        """Send a fill notification to all authorized users.

        Call this from your fill handler to notify via Telegram.
        """
        if not self._config.notify_on_fill:
            return
        text = format_fill_notification(pair, signed_qty, fill_price, when)
        await self._send_to_all(text)

    async def _send_to_all(self, text: str) -> None:
        """Send a message to all authorized users, respecting rate limits."""
        if self._app is None:
            return

        for user_id in self._config.authorized_user_ids:
            wait_time = self._rate_limiter.check(user_id)
            if wait_time > 0:
                logger.debug("Rate limited for user %d, skipping message", user_id)
                continue
            try:
                await self._app.bot.send_message(  # type: ignore[union-attr]
                    chat_id=user_id, text=text, parse_mode="HTML"
                )
            except Exception:  # pragma: no cover
                logger.exception("Failed to send Telegram message to user %d", user_id)

    async def initialize(self) -> None:
        """Build and initialize the Telegram application."""
        auth = self._authenticator

        builder = Application.builder().token(self._config.bot_token)
        self._app = builder.build()

        # Store basana references for handlers.
        self._app.bot_data[KEY_RISK_MANAGER] = self._risk_manager
        self._app.bot_data[KEY_EVENT_DISPATCHER] = self._dispatcher

        # Register command handlers (all wrapped with auth).
        self._app.add_handler(CommandHandler("status", require_auth(auth)(cmd_status)))
        self._app.add_handler(CommandHandler("positions", require_auth(auth)(cmd_positions)))
        self._app.add_handler(CommandHandler("risk", require_auth(auth)(cmd_risk)))
        self._app.add_handler(CommandHandler("kill_switch", require_auth(auth)(cmd_kill_switch)))
        self._app.add_handler(CommandHandler("mode", require_auth(auth)(cmd_mode)))
        self._app.add_handler(CallbackQueryHandler(require_auth(auth)(callback_handler)))

        await self._app.initialize()
        logger.info("Telegram bot initialized")

    async def main(self) -> None:  # pragma: no cover
        """Start polling for Telegram updates."""
        if self._app is None:
            return

        await self._app.start()
        if self._app.updater:
            await self._app.updater.start_polling()

        logger.info("Telegram bot started polling")

        # Keep running until the dispatcher stops.
        while not self._dispatcher.stopped:
            import asyncio

            await asyncio.sleep(1)

    async def finalize(self) -> None:  # pragma: no cover
        """Stop the Telegram bot."""
        if self._app is None:
            return

        if self._app.updater and self._app.updater.running:
            await self._app.updater.stop()
        if self._app.running:
            await self._app.stop()
        await self._app.shutdown()

        logger.info("Telegram bot stopped")
