import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import aiohttp

import basana as bs
from basana.core import event
from .llm_analyzer import LLMAnalyzer
from .thresholds import SignalThresholds

logger = logging.getLogger(__name__)


class LunarCrushSignalEvent(bs.Event):
    def __init__(
        self,
        when: datetime,
        coin: str,
        galaxy_score: float,
        alt_rank: int,
        social_dominance: float,
        social_dominance_ratio: float,
        price: float,
        price_change_24h: float,
        recommendation: str,
        reasoning: str,
        confidence: float,
    ):
        super().__init__(when)
        self.coin = coin
        self.galaxy_score = galaxy_score
        self.alt_rank = alt_rank
        self.social_dominance = social_dominance
        self.social_dominance_ratio = social_dominance_ratio
        self.price = price
        self.price_change_24h = price_change_24h
        self.recommendation = recommendation
        self.reasoning = reasoning
        self.confidence = confidence


class LunarCrushSSESource(event.FifoQueueEventSource, event.Producer):
    """Connects to LunarCrush SSE stream and emits LunarCrushSignalEvent
    when configurable thresholds are exceeded and LLM confirms the signal.

    Extends FifoQueueEventSource + Producer so basana's dispatcher manages
    the producer lifecycle (initialize → main → finalize).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        thresholds: Optional[SignalThresholds] = None,
        llm_analyzer: Optional[LLMAnalyzer] = None,
    ):
        super().__init__(producer=self)
        self._api_key = api_key or os.getenv("LUNARCRUSH_API_KEY", "")
        self._thresholds = thresholds or SignalThresholds()
        self._llm = llm_analyzer or LLMAnalyzer()
        self._social_dominance_history: dict = {}

    async def initialize(self) -> None:
        """Fetch baseline social dominance for threshold comparison."""
        try:
            async with aiohttp.ClientSession() as session:
                for coin in self._thresholds.coins:
                    async with session.get(
                        f"https://lunarcrush.com/api4/public/coins/{coin.lower()}/v1",
                        headers={"Authorization": f"Bearer {self._api_key}"},
                    ) as resp:
                        data = await resp.json()
                        sd = data.get("data", {}).get("social_dominance", 1.0)
                        self._social_dominance_history[coin] = [sd] * 7
                        logger.info(f"Baseline social dominance for {coin}: {sd:.2f}%")
        except Exception as e:
            logger.warning(f"Failed to initialize baseline social dominance: {e}")

    async def main(self) -> None:
        """Producer main loop — connects to SSE stream and processes events."""
        url = "https://lunarcrush.ai/sse"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        while True:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=headers) as resp:
                        logger.info("Connected to LunarCrush SSE stream")
                        async for raw_line in resp.content:
                            line = raw_line.decode("utf-8").strip()
                            if not line.startswith("data:"):
                                continue
                            try:
                                payload = json.loads(line[5:].strip())
                            except json.JSONDecodeError:
                                continue
                            for coin_data in payload.get("data", []):
                                await self._process_coin(coin_data)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"SSE connection lost: {e}. Reconnecting in 5s...")
                await asyncio.sleep(5)

    async def _process_coin(self, coin_data: dict) -> None:
        symbol = coin_data.get("symbol", "").upper()
        if symbol not in self._thresholds.coins:
            return

        galaxy_score = float(coin_data.get("galaxy_score", 0))
        alt_rank = int(coin_data.get("alt_rank", 999))
        social_dominance = float(coin_data.get("social_dominance", 0))
        price = float(coin_data.get("price", 0))
        price_change_24h = float(coin_data.get("percent_change_24h", 0))

        history = self._social_dominance_history.setdefault(symbol, [social_dominance] * 7)
        history.append(social_dominance)
        if len(history) > 7 * 24:
            history.pop(0)
        avg_dominance = sum(history[:-1]) / max(len(history) - 1, 1)
        dominance_ratio = social_dominance / avg_dominance if avg_dominance > 0 else 1.0

        threshold_met = (
            galaxy_score >= self._thresholds.galaxy_score_min
            or alt_rank <= self._thresholds.alt_rank_max
            or dominance_ratio >= self._thresholds.social_dominance_spike
        )
        if not threshold_met:
            return

        logger.info(
            f"Threshold exceeded for {symbol}: galaxy={galaxy_score}, "
            f"rank={alt_rank}, dominance_ratio={dominance_ratio:.2f}x"
        )

        analysis = await self._llm.analyze(
            {
                "coin": symbol,
                "galaxy_score": galaxy_score,
                "alt_rank": alt_rank,
                "social_dominance": social_dominance,
                "social_dominance_ratio": dominance_ratio,
                "price": price,
                "price_change_24h": price_change_24h,
            },
            self._thresholds,
        )

        if analysis.get("recommendation") == "ignore":
            logger.info(f"LLM dismissed signal for {symbol}: {analysis.get('reasoning')}")
            return

        self.push(
            LunarCrushSignalEvent(
                when=datetime.now(timezone.utc),
                coin=symbol,
                galaxy_score=galaxy_score,
                alt_rank=alt_rank,
                social_dominance=social_dominance,
                social_dominance_ratio=dominance_ratio,
                price=price,
                price_change_24h=price_change_24h,
                recommendation=analysis.get("recommendation", "wait"),
                reasoning=analysis.get("reasoning", ""),
                confidence=float(analysis.get("confidence", 0.0)),
            )
        )
