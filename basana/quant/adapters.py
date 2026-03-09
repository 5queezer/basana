from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import List, Optional, Sequence
import datetime
import re

from basana.core import bar, enums, pair

from .signals import NormalizedSignal, SignalSourcePlugin

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,15}$")
_RANKED_ROW_RE = re.compile(
    r"^\|\s*(?P<rank>\d+)\s*\|\s*(?P<symbol>[A-Za-z0-9]+)\s*\|\s*(?P<score>[0-9]+(?:\.[0-9]+)?)\s*\|\s*(?P<secondary_rank>\d+)\s*\|(?:\s*(?P<time>[^|]+?)\s*\|)?\s*$"
)
_ACTION_TEXT_RE = re.compile(
    r"^(?:\[(?P<ts>[^\]]+)\]\s*)?(?P<action>BUY|SELL|LONG|SHORT|EXIT|CLOSE|COVER)\s+(?P<symbol>[A-Z0-9/_-]+)(?:\s+at\s+(?P<price>[0-9]+(?:\.[0-9]+)?))?(?:\s*[\-:]\s*(?P<note>.*))?$",
    re.IGNORECASE,
)


def _coerce_decimal(value: str, field_name: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"invalid {field_name}: {value}") from exc


def _parse_when(value: Optional[str], default_when: datetime.datetime) -> datetime.datetime:
    if value is None or not value.strip():
        return default_when
    text = value.strip().replace("Z", "+00:00")
    if text.endswith(" UTC"):
        text = text[:-4] + "+00:00"
    when = datetime.datetime.fromisoformat(text)
    if when.tzinfo is None:
        when = when.replace(tzinfo=datetime.timezone.utc)
    return when


def _normalize_pair(symbol: str, quote_symbol: str) -> pair.Pair:
    normalized = re.sub(r"[^A-Z0-9]", "", symbol.upper())
    quote_symbol = quote_symbol.upper()
    if not normalized:
        raise ValueError("symbol is empty")
    if normalized.endswith(quote_symbol) and normalized != quote_symbol:
        base = normalized[: -len(quote_symbol)]
    else:
        base = normalized
    if not _SYMBOL_RE.match(base):
        raise ValueError(f"invalid base symbol: {symbol}")
    return pair.Pair(base, quote_symbol)


class ScheduledSignalPlugin(SignalSourcePlugin):
    def __init__(self, signals: Sequence[NormalizedSignal]):
        self._signals = sorted(signals, key=lambda signal: signal.when)
        self._next_index = 0

    async def on_bar(self, bar_event: bar.BarEvent) -> Sequence[NormalizedSignal]:
        ready: List[NormalizedSignal] = []
        while self._next_index < len(self._signals):
            signal = self._signals[self._next_index]
            if signal.when > bar_event.when:
                break
            self._next_index += 1
            if signal.pair == bar_event.bar.pair:
                ready.append(signal)
        return ready


class RankedTableSignalPlugin(ScheduledSignalPlugin):
    @classmethod
    def from_markdown(
        cls,
        markdown: str,
        *,
        default_when: datetime.datetime,
        quote_symbol: str = "USDT",
        source: str = "ranked-table",
        top_n: Optional[int] = None,
    ) -> "RankedTableSignalPlugin":
        return cls(
            parse_ranked_table_signals(
                markdown,
                default_when=default_when,
                quote_symbol=quote_symbol,
                source=source,
                top_n=top_n,
            )
        )


class ActionTextSignalPlugin(ScheduledSignalPlugin):
    @classmethod
    def from_text(
        cls,
        text: str,
        *,
        default_when: datetime.datetime,
        quote_symbol: str = "USDT",
        source: str = "action-text",
    ) -> "ActionTextSignalPlugin":
        return cls(
            parse_action_text_signals(
                text,
                default_when=default_when,
                quote_symbol=quote_symbol,
                source=source,
            )
        )


def parse_ranked_table_signals(
    markdown: str,
    *,
    default_when: datetime.datetime,
    quote_symbol: str = "USDT",
    source: str = "ranked-table",
    top_n: Optional[int] = None,
) -> List[NormalizedSignal]:
    signals: List[NormalizedSignal] = []
    for line in markdown.splitlines():
        match = _RANKED_ROW_RE.match(line.strip())
        if not match:
            continue
        rank = int(match.group("rank"))
        if top_n is not None and rank > top_n:
            continue
        score = _coerce_decimal(match.group("score"), "score")
        if score < 0 or score > 100:
            raise ValueError(f"score out of range: {score}")
        signals.append(
            NormalizedSignal(
                when=_parse_when(match.group("time"), default_when),
                pair=_normalize_pair(match.group("symbol"), quote_symbol),
                position=enums.Position.LONG,
                source=source,
                strength=(score / Decimal("100")).quantize(Decimal("0.001")),
                target_gross_exposure=(Decimal("1") / Decimal(rank)).quantize(Decimal("0.001")),
                metadata={
                    "rank": rank,
                    "score": str(score),
                    "secondary_rank": int(match.group("secondary_rank")),
                },
            )
        )
    if not signals:
        raise ValueError("no ranked table rows found")
    return signals


def parse_action_text_signals(
    text: str,
    *,
    default_when: datetime.datetime,
    quote_symbol: str = "USDT",
    source: str = "action-text",
) -> List[NormalizedSignal]:
    signals: List[NormalizedSignal] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _ACTION_TEXT_RE.match(line)
        if not match:
            raise ValueError(f"unsupported action text format: {raw_line}")
        action = match.group("action").upper()
        position = {
            "BUY": enums.Position.LONG,
            "LONG": enums.Position.LONG,
            "SHORT": enums.Position.SHORT,
            "SELL": enums.Position.NEUTRAL,
            "EXIT": enums.Position.NEUTRAL,
            "CLOSE": enums.Position.NEUTRAL,
            "COVER": enums.Position.NEUTRAL,
        }[action]
        metadata = {"action": action}
        note = match.group("note")
        if note:
            metadata["note"] = note
        price = match.group("price")
        if price is not None:
            metadata["trigger_price"] = price
        signals.append(
            NormalizedSignal(
                when=_parse_when(match.group("ts"), default_when),
                pair=_normalize_pair(match.group("symbol"), quote_symbol),
                position=position,
                source=source,
                strength=Decimal("1"),
                target_gross_exposure=Decimal("1") if position != enums.Position.NEUTRAL else Decimal("0"),
                metadata=metadata,
            )
        )
    if not signals:
        raise ValueError("no action text signals found")
    return signals
