"""
TradingAgents multi-agent analyzer — drop-in replacement for LLMAnalyzer.

Instead of a single LLM call, routes through TradingAgents' full analyst
pipeline (market, social, news, fundamentals + bull/bear debate + risk
managers + portfolio manager) before emitting a basana signal.

Usage:
    from basana.external.lunarcrush.tradingagents_analyzer import TradingAgentsAnalyzer
    from basana.external.lunarcrush.sse_source import LunarCrushSSESource

    analyzer = TradingAgentsAnalyzer(
        llm_provider="openai",
        backend_url="http://localhost:4000",  # LiteLLM proxy
        api_key="...",
        deep_model="claude-sonnet-4-6",
        quick_model="claude-haiku-4-5",
    )
    source = LunarCrushSSESource(llm_analyzer=analyzer)
"""

import asyncio
import logging
import os
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)

# BTC/ETH → yfinance tickers
_COIN_TO_TICKER = {
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
    "SOL": "SOL-USD",
    "BNB": "BNB-USD",
    "AVAX": "AVAX-USD",
    "MATIC": "MATIC-USD",
    "LINK": "LINK-USD",
    "DOT": "DOT-USD",
    "ADA": "ADA-USD",
    "XRP": "XRP-USD",
}

# TradingAgents BUY/HOLD/SELL → basana recommendation
_DECISION_MAP = {
    "BUY": "enter",
    "HOLD": "wait",
    "SELL": "ignore",
}


class TradingAgentsAnalyzer:
    """Multi-agent analyzer using TradingAgents framework.

    Implements the same interface as LLMAnalyzer so it can be swapped in
    without changes to LunarCrushSSESource.

    The full analyst pipeline runs synchronously in a thread pool to keep
    the basana async event loop unblocked.
    """

    def __init__(
        self,
        llm_provider: Optional[str] = None,
        backend_url: Optional[str] = None,
        api_key: Optional[str] = None,
        deep_model: Optional[str] = None,
        quick_model: Optional[str] = None,
        analysts: Optional[list] = None,
        max_debate_rounds: int = 1,
        max_risk_rounds: int = 1,
    ):
        self._provider = llm_provider or os.getenv("LLM_PROVIDER", "openai")
        self._backend_url = backend_url or os.getenv(
            "LLM_API_BASE", "https://api.openai.com/v1"
        )
        self._api_key = api_key or os.getenv("LLM_API_KEY", "")
        self._deep_model = deep_model or os.getenv(
            "LLM_DEEP_MODEL", "gpt-4o"
        )
        self._quick_model = quick_model or os.getenv(
            "LLM_QUICK_MODEL", "gpt-4o-mini"
        )
        self._analysts = analysts or ["market", "social", "news", "fundamentals"]
        self._max_debate = max_debate_rounds
        self._max_risk = max_risk_rounds
        self._graph = None  # lazy-init (import is slow)

    def _build_graph(self):
        """Lazy-import and configure TradingAgentsGraph."""
        try:
            from tradingagents.graph.trading_graph import TradingAgentsGraph
        except ImportError as e:
            raise ImportError(
                "tradingagents not installed. Run: pip install tradingagents-cn"
            ) from e

        config = {
            "llm_provider": self._provider,
            "backend_url": self._backend_url,
            "deep_think_llm": self._deep_model,
            "quick_think_llm": self._quick_model,
            "max_debate_rounds": self._max_debate,
            "max_risk_discuss_rounds": self._max_risk,
            "data_vendors": {
                "core_stock_apis": "yfinance",
                "technical_indicators": "yfinance",
                "fundamental_data": "yfinance",
                "news_data": "yfinance",
            },
        }
        # Set api key env so langchain picks it up
        if self._api_key:
            os.environ["OPENAI_API_KEY"] = self._api_key
            os.environ["OPENAI_BASE_URL"] = self._backend_url

        return TradingAgentsGraph(
            selected_analysts=self._analysts,
            debug=False,
            config=config,
        )

    def _run_sync(self, ticker: str, trade_date: date) -> dict:
        """Run TradingAgents synchronously (called in thread pool)."""
        if self._graph is None:
            self._graph = self._build_graph()

        try:
            _final_state, decision = self._graph.propagate(ticker, str(trade_date))
            decision = (decision or "HOLD").strip().upper()

            # Extract reasoning from final_trade_decision in state
            reasoning = ""
            if hasattr(self._graph, "curr_state") and self._graph.curr_state:
                reasoning = str(
                    self._graph.curr_state.get("final_trade_decision", "")
                )[:300]

            recommendation = _DECISION_MAP.get(decision, "wait")
            confidence = 0.8 if decision == "BUY" else 0.5 if decision == "HOLD" else 0.3

            return {
                "recommendation": recommendation,
                "reasoning": reasoning or f"TradingAgents consensus: {decision}",
                "confidence": confidence,
                "raw_decision": decision,
            }
        except Exception as e:
            logger.warning(f"TradingAgents analysis failed for {ticker}: {e}")
            return {
                "recommendation": "wait",
                "reasoning": f"TradingAgents unavailable: {e}",
                "confidence": 0.0,
            }

    async def analyze(self, data: dict, thresholds: "SignalThresholds") -> dict:
        """Async entry point — runs TradingAgents in a thread pool."""
        coin = data["coin"]
        ticker = _COIN_TO_TICKER.get(coin, f"{coin}-USD")
        trade_date = date.today()

        logger.info(
            f"Running TradingAgents multi-agent analysis for {ticker} ({trade_date})..."
        )

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, self._run_sync, ticker, trade_date
        )

        logger.info(
            f"TradingAgents decision for {coin}: {result['raw_decision']} "
            f"→ {result['recommendation']} (confidence={result['confidence']:.2f})"
        )
        return result
