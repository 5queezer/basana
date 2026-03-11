#!/usr/bin/env python3
"""
Paper Trading Pipeline — Basana Edition (v2)
Updated to use basana.external.telegram (PR #19)

Uses Basana abstractions:
  - bs.Pair / bs.Position / bs.TradingSignal
  - bs.EventDispatcher (async event loop)
  - basana.external.telegram.TelegramConfig / TelegramBot
  - basana.external.telegram.formatters (signal & fill notifications)
  - StructuredMessage for structured logging

State files (format preserved for compatibility):
  - memory/paper_portfolio.json
  - memory/paper_trades.json

Signals:
  - memory/100eyes_alerts.jsonl
  - memory/lc_signals.md

Run: python samples/paper_trader_basana.py [--dry-run]
"""

import asyncio
import importlib.util
import json
import logging
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

import basana as bs
from basana.core.logs import StructuredMessage
from basana.external.telegram import TelegramBot, TelegramConfig, Verbosity
from basana.external.telegram.formatters import (
    format_fill_notification,
    format_signal_notification,
)
from telegram import Bot as TelegramBotClient

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_here = os.path.dirname(os.path.abspath(__file__))
_workspace_candidates = [
    os.path.join(os.path.dirname(os.path.dirname(_here)), ".openclaw", "workspace"),
    os.path.join(os.path.expanduser("~"), ".openclaw", "workspace"),
]
_workspace = next((p for p in _workspace_candidates if os.path.isdir(p)), _workspace_candidates[-1])

ALERTS_FILE          = os.path.join(_workspace, "memory", "100eyes_alerts.jsonl")
LC_SIGNALS_FILE      = os.path.join(_workspace, "memory", "lc_signals.md")
PORTFOLIO_FILE       = os.path.join(_workspace, "memory", "paper_portfolio.json")
TRADES_FILE          = os.path.join(_workspace, "memory", "paper_trades.json")
SIGNAL_STATE_FILE    = os.path.join(_workspace, "memory", "signal_notify_state.json")

# How long to suppress re-notification for the same signal (seconds)
LC_SIGNAL_TTL        = 6 * 3600   # LC signals stable for 6h
ALERT_SIGNAL_TTL     = 90 * 60    # 100eyes: suppress for 90min

# Load technicals helper (optional)
_tc_path = os.path.join(_workspace, "scripts", "technicals_check.py")
technicals = None
if os.path.exists(_tc_path):
    spec = importlib.util.spec_from_file_location("technicals_check", _tc_path)
    technicals = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(technicals)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID    = int(os.environ.get("TELEGRAM_CHAT_ID", "5179244412"))
LUNARCRUSH_API_KEY  = os.environ.get("LUNARCRUSH_API_KEY")

MAX_POSITIONS         = 3
MAX_PORTFOLIO_PCT     = Decimal("0.10")
STOP_LOSS_PCT         = Decimal("-0.08")
TAKE_PROFIT_PCT       = Decimal("0.18")
BREAK_EVEN_TRIGGER    = Decimal("0.05")
TRAILING_STOP_PCT     = Decimal("0.06")
TIME_STOP_HOURS       = 48
MIN_SIGNAL_SCORE      = 2

BULLISH_KEYWORDS = ["bullish", "long", "oversold", "breakout", "squeeze", "support",
                    "golden cross", "fibonacci retracement"]
BEARISH_KEYWORDS = ["bearish", "short", "overbought", "resistance", "death cross"]

LOG_TAG = "[paper_trader]"
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Telegram helpers — using basana.external.telegram + python-telegram-bot
# ---------------------------------------------------------------------------

def load_signal_state() -> dict:
    try:
        if os.path.exists(SIGNAL_STATE_FILE):
            return json.load(open(SIGNAL_STATE_FILE))
    except Exception:
        pass
    return {}


def save_signal_state(state: dict) -> None:
    json.dump(state, open(SIGNAL_STATE_FILE, "w"), indent=2)


def is_signal_seen(state: dict, key: str, direction: str, ttl: int) -> bool:
    """Return True if this (key, direction) was notified within TTL seconds."""
    entry = state.get(key)
    if not entry or entry.get("direction") != direction:
        return False
    try:
        from datetime import timezone as tz
        notified = datetime.fromisoformat(entry["ts"])
        age = (datetime.now(tz=tz.utc) - notified).total_seconds()
        return age < ttl
    except Exception:
        return False


def _make_telegram_config() -> Optional[TelegramConfig]:
    """Build TelegramConfig if a token is available."""
    if not TELEGRAM_BOT_TOKEN:
        return None
    return TelegramConfig(
        bot_token=TELEGRAM_BOT_TOKEN,
        authorized_user_ids=[TELEGRAM_CHAT_ID],
        verbosity=Verbosity.NORMAL,
        notify_on_fill=True,
        notify_on_signal=True,
        notify_on_risk_breach=True,
    )


async def _send_telegram(text: str, parse_mode: str = "HTML") -> None:
    """Send a message via Telegram Bot API using python-telegram-bot."""
    if not TELEGRAM_BOT_TOKEN:
        return
    try:
        bot = TelegramBotClient(token=TELEGRAM_BOT_TOKEN)
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            parse_mode=parse_mode,
        )
    except Exception as exc:
        logger.warning(StructuredMessage("telegram_send_failed", error=str(exc)))


def notify(msg: str, dry_run: bool = False) -> None:
    """Fire-and-forget Telegram notification (sync wrapper)."""
    print(f"{LOG_TAG} NOTIFY: {msg[:120]}")
    if dry_run or not TELEGRAM_BOT_TOKEN:
        return
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(_send_telegram(msg))
        else:
            loop.run_until_complete(_send_telegram(msg))
    except Exception as exc:
        logger.warning(StructuredMessage("notify_failed", error=str(exc)))


# ---------------------------------------------------------------------------
# Price fetching
# ---------------------------------------------------------------------------

def get_price(symbol: str) -> Optional[Decimal]:
    sym = symbol.upper().replace("USDT", "")

    if LUNARCRUSH_API_KEY:
        try:
            url = f"https://lunarcrush.com/api4/public/coins/{sym.lower()}/v1"
            req = urllib.request.Request(
                url, headers={"Authorization": f"Bearer {LUNARCRUSH_API_KEY}"}
            )
            data = json.loads(urllib.request.urlopen(req, timeout=10).read())
            if "data" in data and "price" in data["data"]:
                return Decimal(str(data["data"]["price"]))
        except Exception:
            pass

    if technicals:
        try:
            closes, *_ = technicals.fetch_ohlcv(symbol)
            return Decimal(str(closes[-1]))
        except Exception:
            pass

    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol.upper()}"
        data = json.loads(urllib.request.urlopen(url, timeout=5).read())
        return Decimal(data["price"])
    except Exception as exc:
        logger.warning(StructuredMessage("price_fetch_failed", symbol=symbol, error=str(exc)))
        return None


# ---------------------------------------------------------------------------
# Signal parsers
# ---------------------------------------------------------------------------

def parse_100eyes_alerts() -> List[dict]:
    results = []
    if not os.path.exists(ALERTS_FILE):
        return results

    raw_lines = open(ALERTS_FILE).readlines()
    out_lines = []

    for raw in raw_lines:
        raw = raw.strip()
        if not raw:
            out_lines.append(raw)
            continue
        try:
            alert = json.loads(raw)
        except Exception:
            out_lines.append(raw)
            continue

        if not alert.get("processed", False):
            text = alert.get("text", "")
            text_lower = text.lower()
            tickers = re.findall(r'\[([A-Z]{2,15}USDT)\]', text)
            direction = None
            for kw in BULLISH_KEYWORDS:
                if kw in text_lower:
                    direction = "LONG"
                    break
            if not direction:
                for kw in BEARISH_KEYWORDS:
                    if kw in text_lower:
                        direction = "SHORT"
                        break
            if tickers and direction:
                for ticker in tickers:
                    results.append({
                        "symbol": ticker, "direction": direction,
                        "source": "100eyes", "text": text[:80],
                    })
            alert["processed"] = True
        out_lines.append(json.dumps(alert))

    with open(ALERTS_FILE, "w") as f:
        f.write("\n".join(out_lines) + "\n")
    return results


def parse_lc_signals() -> List[dict]:
    results = []
    if not os.path.exists(LC_SIGNALS_FILE):
        return results

    SKIP = {"SYMBOL", "ALTRANK", "ALTRANKDELTA", "GALAXY", "GALAXYSCORE",
            "CHANGE", "24HCHANGE", "DELTA", "SCORE"}

    def extract_symbols(block: str) -> List[str]:
        syms = []
        for line in block.split("\n"):
            if "|" not in line:
                continue
            cols = [c.strip() for c in line.split("|")]
            for col in cols[1:]:
                if not col or re.match(r'^[-:]+$', col):
                    break
                sym = re.sub(r'[^A-Z0-9]', '', col.upper())
                if 2 <= len(sym) <= 10 and sym not in SKIP:
                    syms.append(sym)
                break
        return syms

    content = open(LC_SIGNALS_FILE).read()
    long_m  = re.search(r'(?i)(LONG SETUP[S]?)(.*?)(?=SHORT SETUP|$)', content, re.S)
    short_m = re.search(r'(?i)(SHORT SETUP[S]?)(.*)', content, re.S)

    if long_m:
        for s in extract_symbols(long_m.group(2)):
            results.append({
                "symbol": s + "USDT" if not s.endswith("USDT") else s,
                "direction": "LONG", "source": "lc",
            })
    if short_m:
        for s in extract_symbols(short_m.group(2)):
            results.append({
                "symbol": s + "USDT" if not s.endswith("USDT") else s,
                "direction": "SHORT", "source": "lc",
            })
    return results


# ---------------------------------------------------------------------------
# Signal scoring + TA validation
# ---------------------------------------------------------------------------

def score_signal(sig: dict) -> Tuple[int, List[str]]:
    score, reasons = 0, []
    source = sig.get("source", "")
    symbol = sig.get("symbol", "")

    if source == "lc":
        score += 2; reasons.append("LunarCrush setup")
    elif source == "100eyes":
        score += 1; reasons.append("100eyes alert")

    MAJORS = {"BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT",
              "XRPUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT"}
    if symbol in MAJORS:
        score += 1; reasons.append("liquid major")

    text = (sig.get("text") or "").lower()
    if any(k in text for k in ["breakout", "squeeze", "golden cross", "support", "resistance"]):
        score += 1; reasons.append("technical keyword")

    return score, reasons


def validate_signal(symbol: str, direction: str) -> Tuple[bool, str]:
    if not technicals:
        return True, "TA skipped (no technicals module)"
    try:
        res = technicals.analyze_direction(symbol, direction)
        verdict = res.get("direction_verdict", "AVOID")
        fails = ", ".join(res.get("direction_fails", [])[:3])
        return verdict == "PASS", f"{verdict}: {fails}" if fails else verdict
    except Exception as exc:
        return False, f"ERROR: {exc}"


# ---------------------------------------------------------------------------
# State I/O
# ---------------------------------------------------------------------------

def load_portfolio() -> dict:
    if os.path.exists(PORTFOLIO_FILE):
        return json.load(open(PORTFOLIO_FILE))
    return {"balance_usd": 10000.0, "starting_balance": 10000.0}

def save_portfolio(p: dict) -> None:
    json.dump(p, open(PORTFOLIO_FILE, "w"), indent=2)

def load_trades() -> dict:
    if os.path.exists(TRADES_FILE):
        return json.load(open(TRADES_FILE))
    return {"open_positions": {}, "closed_trades": []}

def save_trades(t: dict) -> None:
    json.dump(t, open(TRADES_FILE, "w"), indent=2)


# ---------------------------------------------------------------------------
# Paper position manager (Basana-aware, PR #19 Telegram integration)
# ---------------------------------------------------------------------------

class PaperPositionManager:
    """
    Basana-aware paper position manager.

    - Receives bs.TradingSignal events from the dispatcher
    - Manages paper positions with full risk logic
    - Uses basana.external.telegram formatters for structured notifications
    - State persisted in JSON files (compatible with original paper_trader.py)
    """

    def __init__(self, dry_run: bool = False):
        self._dry_run = dry_run

    # ── Basana event interface ──────────────────────────────────────────────

    async def on_trading_signal(self, trading_signal: bs.TradingSignal) -> None:
        pairs = list(trading_signal.get_pairs())
        logger.info(StructuredMessage("trading_signal",
                                      pairs=[(str(p), str(pos)) for p, pos in pairs]))

        for pair, target_position in pairs:
            if target_position == bs.Position.NEUTRAL:
                continue
            direction = "LONG" if target_position == bs.Position.LONG else "SHORT"
            symbol = f"{pair.base_symbol}{pair.quote_symbol}"
            source = getattr(trading_signal, "source", "unknown")
            score  = getattr(trading_signal, "score", MIN_SIGNAL_SCORE)
            when   = getattr(trading_signal, "when", datetime.now(tz=timezone.utc))

            # Use basana formatter for signal notification
            pos_str = target_position.name
            tg_msg = format_signal_notification(pair, pos_str, when)
            tg_msg += f"\nSource: <code>{source} | score={score}</code>"
            notify(tg_msg, self._dry_run)

            price = get_price(symbol)
            if price is None:
                logger.warning(StructuredMessage("no_price", symbol=symbol))
                continue
            self._open_trade(symbol, direction, price, f"{source} | score={score}", when=when)

    # ── Risk / exit management ──────────────────────────────────────────────

    def check_exits(self) -> None:
        trades    = load_trades()
        portfolio = load_portfolio()
        now       = datetime.utcnow()
        symbols   = list(trades["open_positions"].keys())

        for symbol in symbols:
            price = get_price(symbol)
            if price is None:
                logger.warning(StructuredMessage("no_price_for_exit", symbol=symbol))
                continue

            pos = trades["open_positions"].get(symbol)
            if not pos:
                continue

            entry     = Decimal(str(pos["entry_price"]))
            direction = pos["direction"]
            pnl_pct   = (price - entry) / entry
            if direction == "SHORT":
                pnl_pct = -pnl_pct

            if direction == "LONG":
                pos["best_price"]  = float(max(Decimal(str(pos.get("best_price", entry))), price))
                pos["worst_price"] = float(min(Decimal(str(pos.get("worst_price", entry))), price))
                best = Decimal(str(pos["best_price"]))
                trailing_dd = (price - best) / best
            else:
                pos["best_price"]  = float(min(Decimal(str(pos.get("best_price", entry))), price))
                pos["worst_price"] = float(max(Decimal(str(pos.get("worst_price", entry))), price))
                best = Decimal(str(pos["best_price"]))
                trailing_dd = (best - price) / best

            age_h = (now - datetime.fromisoformat(pos["entry_ts"])).total_seconds() / 3600

            logger.info(StructuredMessage(
                "position_check", symbol=symbol, direction=direction,
                entry=float(entry), price=float(price),
                pnl_pct=round(float(pnl_pct) * 100, 2), age_h=round(age_h, 1),
            ))
            print(f"{LOG_TAG} {symbol} ({direction}): entry=${entry:.6g} "
                  f"now=${price:.6g} PnL={pnl_pct*100:+.2f}% age={age_h:.1f}h")

            if pnl_pct >= BREAK_EVEN_TRIGGER:
                pos["break_even_armed"] = True

            reason = None
            if pnl_pct <= STOP_LOSS_PCT:
                reason = "STOP_LOSS"
            elif pos.get("break_even_armed") and pnl_pct <= Decimal("0.005"):
                reason = "BREAK_EVEN_PROTECT"
            elif pnl_pct >= TAKE_PROFIT_PCT:
                reason = "TAKE_PROFIT"
            elif pos.get("break_even_armed") and trailing_dd <= -TRAILING_STOP_PCT:
                reason = "TRAILING_STOP"
            elif age_h >= TIME_STOP_HOURS and pnl_pct < Decimal("0.02"):
                reason = "TIME_STOP"

            if reason:
                self._close_trade(symbol, price, reason, trades, portfolio)
            else:
                trades["open_positions"][symbol] = pos

        save_trades(trades)
        save_portfolio(portfolio)

    # ── Internal trade lifecycle ────────────────────────────────────────────

    def _open_trade(
        self,
        symbol: str,
        direction: str,
        price: Decimal,
        source: str = "",
        when: Optional[datetime] = None,
    ) -> None:
        portfolio = load_portfolio()
        trades    = load_trades()

        if len(trades["open_positions"]) >= MAX_POSITIONS:
            print(f"{LOG_TAG} Max positions ({MAX_POSITIONS}) reached, skipping {symbol}.")
            return
        if symbol in trades["open_positions"]:
            print(f"{LOG_TAG} Already in {symbol}.")
            return

        balance  = Decimal(str(portfolio["balance_usd"]))
        notional = balance * MAX_PORTFOLIO_PCT
        if notional < Decimal("10"):
            print(f"{LOG_TAG} Insufficient balance.")
            return

        qty  = notional / price
        sl   = price * (1 + STOP_LOSS_PCT)
        tp   = price * (1 + TAKE_PROFIT_PCT)
        when = when or datetime.now(tz=timezone.utc)

        # Use basana formatter for fill notification
        signed_qty = qty if direction == "LONG" else -qty
        pair = bs.Pair(symbol.replace("USDT", ""), "USDT")
        fill_msg = format_fill_notification(pair, signed_qty, price, when)
        fill_msg += (
            f"\nNotional: <code>${notional:.2f}</code>\n"
            f"SL: <code>${sl:.6g}</code> | TP: <code>${tp:.6g}</code>\n"
            f"Source: <code>{source}</code>"
        )
        notify(fill_msg, self._dry_run)

        logger.info(StructuredMessage(
            "trade_opened", symbol=symbol, direction=direction,
            price=float(price), notional=float(notional), source=source,
        ))
        print(f"{LOG_TAG} OPENED {direction} {symbol} @ ${price:.6g} "
              f"notional=${notional:.2f} source={source}")

        if not self._dry_run:
            trades["open_positions"][symbol] = {
                "symbol": symbol, "direction": direction,
                "entry_price": float(price), "qty": float(qty),
                "notional_usd": float(notional),
                "entry_ts": datetime.utcnow().isoformat(),
                "source": source,
                "best_price": float(price), "worst_price": float(price),
                "break_even_armed": False, "partial_take_profit_done": False,
            }
            portfolio["balance_usd"] = float(balance - notional)
            save_trades(trades)
            save_portfolio(portfolio)

    def _close_trade(
        self,
        symbol: str,
        price: Decimal,
        reason: str,
        trades: dict,
        portfolio: dict,
    ) -> None:
        pos = trades["open_positions"].get(symbol)
        if not pos:
            return

        entry     = Decimal(str(pos["entry_price"]))
        direction = pos["direction"]
        notional  = Decimal(str(pos["notional_usd"]))
        qty       = Decimal(str(pos["qty"]))

        pnl_pct = (price - entry) / entry
        if direction == "SHORT":
            pnl_pct = -pnl_pct
        pnl_usd     = notional * pnl_pct
        exit_value  = notional + pnl_usd
        new_balance = Decimal(str(portfolio["balance_usd"])) + exit_value

        emoji = "✅" if pnl_usd >= 0 else "🔴"
        when  = datetime.now(tz=timezone.utc)

        # Use basana formatter for fill notification (close = reverse qty)
        signed_qty = -qty if direction == "LONG" else qty
        pair = bs.Pair(symbol.replace("USDT", ""), "USDT")
        fill_msg = format_fill_notification(pair, signed_qty, price, when)
        fill_msg += (
            f"\n{emoji} Reason: <code>{reason}</code>\n"
            f"P&amp;L: <code>{pnl_pct*100:+.2f}% (${pnl_usd:+.2f})</code>\n"
            f"Balance: <code>${new_balance:.2f}</code>"
        )
        notify(fill_msg, self._dry_run)

        logger.info(StructuredMessage(
            "trade_closed", symbol=symbol, direction=direction,
            entry=float(entry), exit=float(price),
            pnl_pct=round(float(pnl_pct) * 100, 2),
            pnl_usd=round(float(pnl_usd), 2), reason=reason,
        ))
        print(f"{LOG_TAG} CLOSED {direction} {symbol} @ ${price:.6g} "
              f"PnL={pnl_pct*100:+.2f}% (${pnl_usd:+.2f}) reason={reason}")

        if not self._dry_run:
            closed = {
                **pos,
                "exit_price": float(price),
                "exit_ts": datetime.utcnow().isoformat(),
                "pnl_pct": float(pnl_pct),
                "pnl_usd": float(pnl_usd),
                "reason": reason,
            }
            del trades["open_positions"][symbol]
            trades["closed_trades"].append(closed)
            portfolio["balance_usd"] = float(new_balance)


# ---------------------------------------------------------------------------
# Basana signal source
# ---------------------------------------------------------------------------

class FileSignalSource:
    """
    Reads 100eyes + LunarCrush signal files, scores, validates,
    and dispatches bs.TradingSignal events.
    """

    def __init__(self, position_manager: PaperPositionManager):
        self._pm = position_manager

    async def run_once(self) -> None:
        alerts  = parse_100eyes_alerts()
        lc_sigs = parse_lc_signals()
        all_signals = alerts + lc_sigs

        print(f"{LOG_TAG} Signals: {len(alerts)} 100eyes, {len(lc_sigs)} LC")
        logger.info(StructuredMessage("signals_found", alerts=len(alerts), lc=len(lc_sigs)))

        state = load_signal_state()
        state_dirty = False

        for sig in all_signals:
            symbol    = sig["symbol"]
            direction = sig["direction"]
            source    = sig.get("source", "?")
            score, reasons = score_signal(sig)

            print(f"{LOG_TAG} {direction} {symbol} [{source}] score={score} "
                  f"reasons={'; '.join(reasons) or 'n/a'}")

            if score < MIN_SIGNAL_SCORE:
                print(f"{LOG_TAG}   -> score too low, skip")
                continue

            valid, verdict = validate_signal(symbol, direction)
            if not valid:
                print(f"{LOG_TAG}   -> TA verdict={verdict}, skip")
                continue

            # ── Dedup: skip notification if same signal was sent recently ──
            ttl = LC_SIGNAL_TTL if source == "lc" else ALERT_SIGNAL_TTL
            state_key = f"{source}:{symbol}"
            if is_signal_seen(state, state_key, direction, ttl):
                print(f"{LOG_TAG}   -> already notified ({source}), skip")
                continue

            # Mark as seen before dispatching
            state[state_key] = {
                "direction": direction,
                "source":    source,
                "ts":        datetime.now(tz=timezone.utc).isoformat(),
            }
            state_dirty = True
            # ──────────────────────────────────────────────────────────────

            base     = symbol.replace("USDT", "")
            pair     = bs.Pair(base, "USDT")
            position = bs.Position.LONG if direction == "LONG" else bs.Position.SHORT
            when     = datetime.now(tz=timezone.utc)

            trading_signal = bs.TradingSignal(when=when, op_or_pos=position, pair=pair)
            trading_signal.source = source   # type: ignore[attr-defined]
            trading_signal.score  = score    # type: ignore[attr-defined]
            trading_signal.when   = when     # type: ignore[attr-defined]

            await self._pm.on_trading_signal(trading_signal)

        if state_dirty:
            save_signal_state(state)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(dry_run: bool = False) -> None:
    portfolio = load_portfolio()
    trades    = load_trades()
    open_pos  = trades["open_positions"]
    closed    = trades["closed_trades"]

    realized = sum(t.get("pnl_usd", 0) for t in closed)
    equity   = Decimal(str(portfolio["balance_usd"]))
    for sym, pos in open_pos.items():
        px = get_price(sym)
        if not px:
            continue
        pnl_pct = (px - Decimal(str(pos["entry_price"]))) / Decimal(str(pos["entry_price"]))
        if pos["direction"] == "SHORT":
            pnl_pct = -pnl_pct
        equity += Decimal(str(pos["notional_usd"])) * (1 + pnl_pct)

    start         = Decimal(str(portfolio.get("starting_balance", 10000)))
    total_pnl_pct = (equity / start - 1) * 100

    summary_lines = [
        "<b>📊 Paper Trader Summary</b>",
        f"Balance: <code>${portfolio['balance_usd']:.2f}</code>",
        f"Equity:  <code>${equity:.2f}</code>  (<code>{total_pnl_pct:+.2f}%</code>)",
        f"Open: <code>{len(open_pos)}</code>  Closed: <code>{len(closed)}</code>  "
        f"Realized P&amp;L: <code>${realized:+.2f}</code>",
    ]
    if open_pos:
        summary_lines.append("")
        for sym, pos in open_pos.items():
            summary_lines.append(
                f"  {pos['direction']} <b>{sym}</b> @ <code>${pos['entry_price']:.6g}</code>"
            )

    summary_html = "\n".join(summary_lines)
    notify(summary_html, dry_run)

    print(f"\n{LOG_TAG} === SUMMARY ===")
    print(f"{LOG_TAG} Balance: ${portfolio['balance_usd']:.2f} | "
          f"Equity: ${equity:.2f} ({total_pnl_pct:+.2f}%)")
    print(f"{LOG_TAG} Open: {len(open_pos)} | Closed: {len(closed)} | "
          f"Realized PnL: ${realized:+.2f}")
    for sym, pos in open_pos.items():
        print(f"{LOG_TAG}   {pos['direction']} {sym} @ ${pos['entry_price']:.6g}")

    logger.info(StructuredMessage(
        "summary",
        balance=portfolio["balance_usd"],
        equity=float(equity),
        total_pnl_pct=round(float(total_pnl_pct), 2),
        open_positions=len(open_pos),
        closed_trades=len(closed),
        realized_pnl=round(realized, 2),
    ))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main(dry_run: bool = False) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    print(f"{LOG_TAG} --- Paper Trader v2 (Basana + telegram PR#19) "
          f"{'[DRY RUN] ' if dry_run else ''}@ {datetime.utcnow().isoformat()} ---")

    if not os.path.exists(PORTFOLIO_FILE):
        save_portfolio({"balance_usd": 10000.0, "starting_balance": 10000.0})
        print(f"{LOG_TAG} Initialized portfolio: $10,000")
    if not os.path.exists(TRADES_FILE):
        save_trades({"open_positions": {}, "closed_trades": []})
        print(f"{LOG_TAG} Initialized trades file")

    dispatcher = bs.realtime_dispatcher()
    pm         = PaperPositionManager(dry_run=dry_run)
    source     = FileSignalSource(pm)

    # Wire up TelegramBot if token is configured (NORMAL verbosity, no RiskManager)
    tg_config = _make_telegram_config()
    if tg_config:
        _tg_bot = TelegramBot(config=tg_config, event_dispatcher=dispatcher)
        logger.info(StructuredMessage("telegram_bot_registered",
                                      verbosity=tg_config.verbosity.value))

    # 1. Check exits on open positions
    pm.check_exits()

    # 2. Parse signals and open new trades
    await source.run_once()

    # 3. Summary
    print_summary(dry_run)

    print(f"{LOG_TAG} --- Done ---")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    asyncio.run(main(dry_run=dry_run))
