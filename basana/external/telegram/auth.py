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

from typing import Set
import functools
import logging


logger = logging.getLogger(__name__)


class UserAuthenticator:
    """Validates Telegram users against an allowlist.

    :param authorized_user_ids: Set of allowed Telegram user IDs.
    """

    def __init__(self, authorized_user_ids: Set[int]):
        self._authorized_ids = frozenset(authorized_user_ids)

    def is_authorized(self, user_id: int) -> bool:
        """Check if a user ID is in the allowlist."""
        return user_id in self._authorized_ids


def require_auth(authenticator: UserAuthenticator):
    """Decorator factory that blocks unauthorized users from executing a handler.

    :param authenticator: The authenticator to check against.
    """

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(update, context):
            user_id = update.effective_user.id if update.effective_user else None
            if user_id is None or not authenticator.is_authorized(user_id):
                logger.warning("Unauthorized Telegram access attempt from user_id=%s", user_id)
                if update.effective_message:
                    await update.effective_message.reply_text("Unauthorized.")
                return
            return await func(update, context)

        return wrapper

    return decorator
