"""
LunarCrush SSE Signal Strategy — Paper Trading Example

Usage:
    LUNARCRUSH_API_KEY=... LLM_API_KEY=... python samples/lunarcrush_signal_strategy.py

Environment variables:
    LUNARCRUSH_API_KEY  - LunarCrush API key
    LLM_API_BASE        - LLM API base URL (default: https://openrouter.ai/api/v1)
    LLM_API_KEY         - LLM API key
    LLM_MODEL           - Model (default: anthropic/claude-haiku-4-5)
"""

import asyncio
import logging
import os

import basana as bs
from basana.external.lunarcrush import LunarCrushSSESource, LunarCrushSignalEvent, SignalThresholds
from basana.external.lunarcrush.llm_analyzer import LLMAnalyzer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


class PaperTradingStrategy:
    def __init__(self, initial_capital: float = 10_000.0):
        self.positions: dict = {}
        self.cash = initial_capital
        self.trades = []

    async def on_signal(self, event: LunarCrushSignalEvent) -> None:
        logger.info(
            "[SIGNAL] %s | %s (confidence=%.2f) | Galaxy=%.1f AltRank=%d Dominance=%.1fx | %s",
            event.coin, event.recommendation.upper(), event.confidence,
            event.galaxy_score, event.alt_rank, event.social_dominance_ratio, event.reasoning,
        )
        if event.recommendation == "enter" and self.positions.get(event.coin, 0.0) == 0:
            allocation = self.cash * 0.10
            size = allocation / event.price
            self.positions[event.coin] = size
            self.cash -= allocation
            self.trades.append({"action": "buy", "coin": event.coin, "price": event.price, "size": size})
            logger.info("[PAPER BUY] %.6f %s @ $%.4f (value=$%.2f)", size, event.coin, event.price, allocation)
        elif event.recommendation == "wait":
            logger.info("[HOLD] Waiting for better entry on %s", event.coin)


async def main() -> None:
    dispatcher = bs.realtime_dispatcher()
    strategy = PaperTradingStrategy(initial_capital=10_000.0)
    thresholds = SignalThresholds(
        coins=["ETH", "BTC"], galaxy_score_min=65.0, social_dominance_spike=2.0, alt_rank_max=20
    )
    source = LunarCrushSSESource(
        api_key=os.getenv("LUNARCRUSH_API_KEY"), thresholds=thresholds, llm_analyzer=LLMAnalyzer()
    )
    dispatcher.subscribe(source, strategy.on_signal)
    await dispatcher.run()


if __name__ == "__main__":
    asyncio.run(main())
