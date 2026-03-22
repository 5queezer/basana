"""
LunarCrush SSE + TradingAgents Multi-Agent Strategy — Paper Trading Example

Replaces the single LLM call with TradingAgents' full analyst pipeline:
  market analyst → social analyst → news analyst → fundamentals analyst
  → bull/bear debate → risk managers → portfolio manager → BUY/HOLD/SELL

Usage:
    LUNARCRUSH_API_KEY=... LLM_API_KEY=... python samples/lunarcrush_tradingagents_strategy.py

With LiteLLM proxy for Claude Max (no per-token costs):
    LLM_PROVIDER=openai \\
    LLM_API_BASE=http://localhost:4000 \\
    LLM_API_KEY=anything \\
    LLM_DEEP_MODEL=claude-sonnet-4-6 \\
    LLM_QUICK_MODEL=claude-haiku-4-5 \\
    LUNARCRUSH_API_KEY=... \\
    python samples/lunarcrush_tradingagents_strategy.py

Environment variables:
    LUNARCRUSH_API_KEY  - LunarCrush API key
    LLM_PROVIDER        - LLM provider (default: openai — works with any OpenAI-compat endpoint)
    LLM_API_BASE        - LLM API base URL (default: https://api.openai.com/v1)
    LLM_API_KEY         - LLM API key
    LLM_DEEP_MODEL      - Model for deep analysis (default: gpt-4o)
    LLM_QUICK_MODEL     - Model for quick decisions (default: gpt-4o-mini)
"""

import asyncio
import logging
import os

import basana as bs
from basana.external.lunarcrush import LunarCrushSSESource, LunarCrushSignalEvent, SignalThresholds
from basana.external.lunarcrush.tradingagents_analyzer import TradingAgentsAnalyzer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


class PaperTradingStrategy:
    def __init__(self, initial_capital: float = 10_000.0):
        self.positions: dict = {}
        self.cash = initial_capital
        self.trades = []

    async def on_signal(self, event: LunarCrushSignalEvent) -> None:
        logger.info(
            "[SIGNAL] %s | %s (confidence=%.2f) | Galaxy=%.1f AltRank=%d Dominance=%.1fx",
            event.coin, event.recommendation.upper(), event.confidence,
            event.galaxy_score, event.alt_rank, event.social_dominance_ratio,
        )
        logger.info("[REASONING] %s", event.reasoning)

        if event.recommendation == "enter" and self.positions.get(event.coin, 0.0) == 0:
            allocation = self.cash * 0.10
            size = allocation / event.price
            self.positions[event.coin] = size
            self.cash -= allocation
            self.trades.append({
                "action": "buy",
                "coin": event.coin,
                "price": event.price,
                "size": size,
            })
            logger.info(
                "[PAPER BUY] %.6f %s @ $%.4f (value=$%.2f)",
                size, event.coin, event.price, allocation,
            )

        elif event.recommendation == "wait":
            logger.info("[HOLD] Waiting for better entry on %s", event.coin)


async def main() -> None:
    dispatcher = bs.realtime_dispatcher()
    strategy = PaperTradingStrategy(initial_capital=10_000.0)

    thresholds = SignalThresholds(
        coins=["ETH", "BTC"],
        galaxy_score_min=65.0,
        social_dominance_spike=2.0,
        alt_rank_max=20,
    )

    # TradingAgentsAnalyzer: full multi-agent consensus replaces single LLM call.
    # Point LLM_API_BASE at your LiteLLM proxy to use Claude Max at zero marginal cost.
    analyzer = TradingAgentsAnalyzer(
        llm_provider=os.getenv("LLM_PROVIDER", "openai"),
        backend_url=os.getenv("LLM_API_BASE", "https://api.openai.com/v1"),
        api_key=os.getenv("LLM_API_KEY", ""),
        deep_model=os.getenv("LLM_DEEP_MODEL", "gpt-4o"),
        quick_model=os.getenv("LLM_QUICK_MODEL", "gpt-4o-mini"),
        analysts=["market", "social", "news", "fundamentals"],
        max_debate_rounds=1,
        max_risk_rounds=1,
    )

    source = LunarCrushSSESource(
        api_key=os.getenv("LUNARCRUSH_API_KEY"),
        thresholds=thresholds,
        llm_analyzer=analyzer,
    )

    dispatcher.subscribe(source, strategy.on_signal)

    logger.info("Starting LunarCrush SSE stream with TradingAgents analysis...")
    await dispatcher.run()


if __name__ == "__main__":
    asyncio.run(main())
