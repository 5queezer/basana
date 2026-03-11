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

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from basana.core.risk.types import DeploymentMode
from basana.external.telegram import formatters


logger = logging.getLogger(__name__)

# Keys used in context.bot_data to store basana references.
KEY_RISK_MANAGER = "risk_manager"
KEY_EVENT_DISPATCHER = "event_dispatcher"


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status — show portfolio summary."""
    risk_mgr = context.bot_data.get(KEY_RISK_MANAGER)
    if risk_mgr is None:
        await update.effective_message.reply_text("Risk manager not configured.")  # type: ignore[union-attr]
        return

    evt_dispatcher = context.bot_data[KEY_EVENT_DISPATCHER]
    now = evt_dispatcher.now()
    snapshot = risk_mgr.portfolio.snapshot(now)
    text = formatters.format_portfolio_summary(snapshot)
    await update.effective_message.reply_text(text, parse_mode="HTML")  # type: ignore[union-attr]


async def cmd_positions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /positions — show open positions."""
    risk_mgr = context.bot_data.get(KEY_RISK_MANAGER)
    if risk_mgr is None:
        await update.effective_message.reply_text("Risk manager not configured.")  # type: ignore[union-attr]
        return

    evt_dispatcher = context.bot_data[KEY_EVENT_DISPATCHER]
    now = evt_dispatcher.now()
    snapshot = risk_mgr.portfolio.snapshot(now)
    text = formatters.format_positions_list(snapshot)
    await update.effective_message.reply_text(text, parse_mode="HTML")  # type: ignore[union-attr]


async def cmd_risk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /risk — show risk manager status."""
    risk_mgr = context.bot_data.get(KEY_RISK_MANAGER)
    if risk_mgr is None:
        await update.effective_message.reply_text("Risk manager not configured.")  # type: ignore[union-attr]
        return

    text = formatters.format_risk_status(
        mode=risk_mgr.mode,
        kill_switch_active=risk_mgr.kill_switch_active,
        kill_switch_reason=risk_mgr.kill_switch_reason,
    )
    await update.effective_message.reply_text(text, parse_mode="HTML")  # type: ignore[union-attr]


async def cmd_kill_switch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /kill_switch [on|off] [reason] — toggle the kill switch."""
    risk_mgr = context.bot_data.get(KEY_RISK_MANAGER)
    if risk_mgr is None:
        await update.effective_message.reply_text("Risk manager not configured.")  # type: ignore[union-attr]
        return

    args = context.args or []
    if not args:
        status = "ACTIVE" if risk_mgr.kill_switch_active else "inactive"
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            f"Kill switch is currently <b>{status}</b>.\nUsage: /kill_switch on|off [reason]",
            parse_mode="HTML",
        )
        return

    action = args[0].lower()
    if action == "on":
        reason = " ".join(args[1:]) if len(args) > 1 else "Activated via Telegram"
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Confirm", callback_data=f"kill_on:{reason}"),
                InlineKeyboardButton("Cancel", callback_data="kill_cancel"),
            ]
        ])
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            f"Activate kill switch with reason: <b>{reason}</b>?",
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    elif action == "off":
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Confirm", callback_data="kill_off"),
                InlineKeyboardButton("Cancel", callback_data="kill_cancel"),
            ]
        ])
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "Deactivate kill switch?",
            reply_markup=keyboard,
        )
    else:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "Usage: /kill_switch on|off [reason]"
        )


async def cmd_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /mode [monitor|paper|live] — switch deployment mode."""
    risk_mgr = context.bot_data.get(KEY_RISK_MANAGER)
    if risk_mgr is None:
        await update.effective_message.reply_text("Risk manager not configured.")  # type: ignore[union-attr]
        return

    args = context.args or []
    if not args:
        text = formatters.format_deployment_mode(risk_mgr.mode)
        await update.effective_message.reply_text(text, parse_mode="HTML")  # type: ignore[union-attr]
        return

    mode_str = args[0].lower()
    try:
        new_mode = DeploymentMode(mode_str)
    except ValueError:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "Invalid mode. Use: monitor, paper, or live."
        )
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Confirm", callback_data=f"mode:{new_mode.value}"),
            InlineKeyboardButton("Cancel", callback_data="mode_cancel"),
        ]
    ])
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        f"Switch deployment mode to <b>{new_mode.value.upper()}</b>?",
        parse_mode="HTML",
        reply_markup=keyboard,
    )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline keyboard button presses."""
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]
    data: str = query.data or ""  # type: ignore[union-attr]
    risk_mgr = context.bot_data.get(KEY_RISK_MANAGER)

    if data.startswith("kill_on:"):
        reason = data[len("kill_on:"):]
        if risk_mgr:
            risk_mgr.activate_kill_switch(reason)
        await query.edit_message_text("Kill switch <b>ACTIVATED</b>.", parse_mode="HTML")  # type: ignore[union-attr]

    elif data == "kill_off":
        if risk_mgr:
            risk_mgr.deactivate_kill_switch()
        await query.edit_message_text("Kill switch <b>deactivated</b>.", parse_mode="HTML")  # type: ignore[union-attr]

    elif data.startswith("mode:"):  # pragma: no branch
        mode_str = data[len("mode:"):]
        new_mode = DeploymentMode(mode_str)
        if risk_mgr:
            risk_mgr.set_mode(new_mode)
        text = formatters.format_deployment_mode(new_mode)
        await query.edit_message_text(text, parse_mode="HTML")  # type: ignore[union-attr]

    elif data in ("kill_cancel", "mode_cancel"):
        await query.edit_message_text("Cancelled.")  # type: ignore[union-attr]
