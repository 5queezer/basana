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

from typing import Dict

from basana.core.token_bucket import TokenBucketLimiter


class UserRateLimiter:
    """Per-user rate limiter for outgoing Telegram messages.

    :param messages_per_minute: Maximum messages per user per minute.
    """

    def __init__(self, messages_per_minute: int):
        self._messages_per_minute = messages_per_minute
        self._limiters: Dict[int, TokenBucketLimiter] = {}

    def _get_limiter(self, user_id: int) -> TokenBucketLimiter:
        if user_id not in self._limiters:
            self._limiters[user_id] = TokenBucketLimiter(
                tokens_per_period=self._messages_per_minute,
                period_duration=60,
                initial_tokens=self._messages_per_minute,
            )
        return self._limiters[user_id]

    def check(self, user_id: int) -> float:
        """Consume a token and return wait time. Returns 0.0 if under limit."""
        return self._get_limiter(user_id).consume()

    async def wait(self, user_id: int) -> None:
        """Wait until a message can be sent without exceeding the rate limit."""
        await self._get_limiter(user_id).wait()
