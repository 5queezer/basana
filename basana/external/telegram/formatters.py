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

from decimal import Decimal
from typing import Optional
import datetime

from basana.core.pair import Pair
from basana.core.risk.types import DeploymentMode, PortfolioSnapshot


def format_portfolio_summary(snapshot: PortfolioSnapshot) -> str:
    """Format a portfolio snapshot as an HTML message for Telegram."""
    lines = [
        "<b>Portfolio Summary</b>",
        f"Time: <code>{snapshot.when:%Y-%m-%d %H:%M:%S UTC}</code>",
        "",
        f"Equity: <code>{snapshot.total_equity:.2f}</code>",
        f"Gross Exposure: <code>{snapshot.gross_exposure:.2f}</code>",
        f"Net Exposure: <code>{snapshot.net_exposure:.2f}</code>",
        f"Unrealized P&L: <code>{_format_pnl(snapshot.unrealized_pnl)}</code>",
        f"Realized P&L (today): <code>{_format_pnl(snapshot.realized_pnl_today)}</code>",
        f"Open Positions: <code>{len(snapshot.positions)}</code>",
    ]
    return "\n".join(lines)


def format_positions_list(snapshot: PortfolioSnapshot) -> str:
    """Format all open positions as an HTML message."""
    if not snapshot.positions:
        return "No open positions."

    lines = ["<b>Open Positions</b>", ""]
    for pos in snapshot.positions.values():
        side = "LONG" if pos.signed_qty > 0 else "SHORT"
        lines.append(
            f"<b>{pos.pair}</b> {side}\n"
            f"  Qty: <code>{pos.signed_qty}</code>\n"
            f"  Entry: <code>{pos.avg_entry_price}</code>\n"
            f"  Current: <code>{pos.current_price}</code>\n"
            f"  P&L: <code>{_format_pnl(pos.unrealized_pnl)}</code>"
        )
        lines.append("")
    return "\n".join(lines).rstrip()


def format_fill_notification(
    pair: Pair,
    signed_qty: Decimal,
    fill_price: Decimal,
    when: datetime.datetime,
) -> str:
    """Format a fill notification as an HTML message."""
    side = "BUY" if signed_qty > 0 else "SELL"
    return (
        f"<b>Fill: {pair}</b>\n"
        f"Side: <code>{side}</code>\n"
        f"Qty: <code>{abs(signed_qty)}</code>\n"
        f"Price: <code>{fill_price}</code>\n"
        f"Time: <code>{when:%H:%M:%S UTC}</code>"
    )


def format_signal_notification(pair: Pair, position: str, when: datetime.datetime) -> str:
    """Format a trading signal notification as an HTML message."""
    return f"<b>Signal: {pair}</b>\nPosition: <code>{position}</code>\nTime: <code>{when:%H:%M:%S UTC}</code>"


def format_risk_status(
    mode: DeploymentMode,
    kill_switch_active: bool,
    kill_switch_reason: Optional[str],
) -> str:
    """Format risk manager status as an HTML message."""
    kill_status = "ACTIVE" if kill_switch_active else "inactive"
    lines = [
        "<b>Risk Status</b>",
        f"Mode: <code>{mode.value.upper()}</code>",
        f"Kill Switch: <code>{kill_status}</code>",
    ]
    if kill_switch_active and kill_switch_reason:
        lines.append(f"Reason: <code>{kill_switch_reason}</code>")
    return "\n".join(lines)


def format_deployment_mode(mode: DeploymentMode) -> str:
    """Format a deployment mode change confirmation."""
    return f"Deployment mode set to <b>{mode.value.upper()}</b>."


def _format_pnl(value: Decimal) -> str:
    """Format a P&L value with sign."""
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}"
