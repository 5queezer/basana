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

from typing import List
import dataclasses
import enum


class Verbosity(enum.Enum):
    """Controls which events trigger Telegram notifications."""

    #: Only fills.
    QUIET = "quiet"
    #: Fills, signals, and risk breaches.
    NORMAL = "normal"
    #: All events including bar updates.
    VERBOSE = "verbose"


@dataclasses.dataclass(frozen=True)
class TelegramConfig:
    """Configuration for the Telegram bot.

    :param bot_token: Telegram Bot API token.
    :param authorized_user_ids: List of Telegram user IDs allowed to interact with the bot.
    :param verbosity: Notification verbosity level.
    :param rate_limit_messages_per_minute: Maximum outgoing messages per user per minute.
    :param notify_on_fill: Send notifications on order fills.
    :param notify_on_signal: Send notifications on trading signals.
    :param notify_on_risk_breach: Send notifications on risk limit breaches.
    """

    bot_token: str
    authorized_user_ids: List[int]
    verbosity: Verbosity = Verbosity.NORMAL
    rate_limit_messages_per_minute: int = 30
    notify_on_fill: bool = True
    notify_on_signal: bool = True
    notify_on_risk_breach: bool = True
