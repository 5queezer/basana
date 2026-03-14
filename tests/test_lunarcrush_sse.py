"""Tests for LunarCrush SSE signal source.

Tests use mocked SSE streams and LLM responses — no real network calls.
"""

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from basana.external.lunarcrush import LunarCrushSSESource, LunarCrushSignalEvent, SignalThresholds
from basana.external.lunarcrush.llm_analyzer import LLMAnalyzer
from basana.external.lunarcrush.thresholds import SignalThresholds


# ---------------------------------------------------------------------------
# SignalThresholds
# ---------------------------------------------------------------------------

def test_thresholds_defaults():
    t = SignalThresholds()
    assert t.galaxy_score_min == 65.0
    assert t.social_dominance_spike == 2.0
    assert t.alt_rank_max == 20
    assert "BTC" in t.coins
    assert "ETH" in t.coins


def test_thresholds_custom():
    t = SignalThresholds(coins=["SOL"], galaxy_score_min=70.0, alt_rank_max=10)
    assert t.coins == ["SOL"]
    assert t.galaxy_score_min == 70.0
    assert t.alt_rank_max == 10


# ---------------------------------------------------------------------------
# LunarCrushSignalEvent
# ---------------------------------------------------------------------------

def test_signal_event_fields():
    now = datetime.now(timezone.utc)
    evt = LunarCrushSignalEvent(
        when=now,
        coin="BTC",
        galaxy_score=72.5,
        alt_rank=5,
        social_dominance=8.3,
        social_dominance_ratio=3.1,
        price=65000.0,
        price_change_24h=4.2,
        recommendation="enter",
        reasoning="Strong breakout confirmed",
        confidence=0.85,
    )
    assert evt.coin == "BTC"
    assert evt.galaxy_score == 72.5
    assert evt.recommendation == "enter"
    assert evt.confidence == 0.85
    assert evt.when == now


# ---------------------------------------------------------------------------
# LLMAnalyzer
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_analyzer_returns_enter():
    mock_response = {"recommendation": "enter", "reasoning": "Strong signal", "confidence": 0.9}

    analyzer = LLMAnalyzer(api_base="http://mock", api_key="test", model="test-model")

    with patch("aiohttp.ClientSession") as mock_session_cls:
        mock_resp = AsyncMock()
        mock_resp.json = AsyncMock(return_value={
            "choices": [{"message": {"content": json.dumps(mock_response)}}]
        })
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_post = AsyncMock()
        mock_post.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_post.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_post)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_session_cls.return_value = mock_session

        thresholds = SignalThresholds()
        result = await analyzer.analyze(
            {
                "coin": "BTC",
                "galaxy_score": 72.0,
                "alt_rank": 8,
                "social_dominance": 6.5,
                "social_dominance_ratio": 2.5,
                "price": 65000.0,
                "price_change_24h": 3.1,
            },
            thresholds,
        )

    assert result["recommendation"] == "enter"
    assert result["confidence"] == 0.9


@pytest.mark.asyncio
async def test_llm_analyzer_fallback_on_error():
    """When the LLM call fails, falls back to recommendation='wait'."""
    analyzer = LLMAnalyzer(api_base="http://mock", api_key="test", model="test-model")

    with patch("aiohttp.ClientSession") as mock_session_cls:
        mock_session = AsyncMock()
        mock_session.post = MagicMock(side_effect=Exception("connection refused"))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_cls.return_value = mock_session

        result = await analyzer.analyze(
            {"coin": "ETH", "galaxy_score": 68.0, "alt_rank": 12,
             "social_dominance": 4.0, "social_dominance_ratio": 2.1,
             "price": 3200.0, "price_change_24h": 1.5},
            SignalThresholds(),
        )

    assert result["recommendation"] == "wait"
    assert "unavailable" in result["reasoning"].lower()


@pytest.mark.asyncio
async def test_llm_analyzer_handles_markdown_json():
    """LLM sometimes wraps JSON in ```json blocks — should still parse."""
    raw = '```json\n{"recommendation": "ignore", "reasoning": "noise", "confidence": 0.2}\n```'
    analyzer = LLMAnalyzer(api_base="http://mock", api_key="test", model="test-model")

    with patch("aiohttp.ClientSession") as mock_session_cls:
        mock_resp = AsyncMock()
        mock_resp.json = AsyncMock(return_value={
            "choices": [{"message": {"content": raw}}]
        })
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_post = AsyncMock()
        mock_post.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_post.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_post)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_cls.return_value = mock_session

        result = await analyzer.analyze(
            {"coin": "BTC", "galaxy_score": 55.0, "alt_rank": 30,
             "social_dominance": 2.0, "social_dominance_ratio": 1.1,
             "price": 60000.0, "price_change_24h": -0.5},
            SignalThresholds(),
        )

    assert result["recommendation"] == "ignore"


# ---------------------------------------------------------------------------
# LunarCrushSSESource — threshold filtering
# ---------------------------------------------------------------------------

def _make_coin_data(symbol="BTC", galaxy_score=50.0, alt_rank=50, social_dominance=2.0,
                    price=65000.0, price_change_24h=1.0):
    return {
        "symbol": symbol,
        "galaxy_score": galaxy_score,
        "alt_rank": alt_rank,
        "social_dominance": social_dominance,
        "percent_change_24h": price_change_24h,
        "price": price,
    }


@pytest.mark.asyncio
async def test_below_threshold_no_event():
    """Coin data below all thresholds should NOT trigger LLM or emit event."""
    mock_llm = AsyncMock()
    mock_llm.analyze = AsyncMock(return_value={"recommendation": "ignore", "reasoning": "", "confidence": 0.0})

    source = LunarCrushSSESource(
        api_key="test",
        thresholds=SignalThresholds(coins=["BTC"], galaxy_score_min=65.0, alt_rank_max=20),
        llm_analyzer=mock_llm,
    )

    # Seed history so ratio doesn't spike
    source._social_dominance_history["BTC"] = [2.0] * 7

    coin_data = _make_coin_data("BTC", galaxy_score=40.0, alt_rank=50, social_dominance=2.0)
    await source._process_coin(coin_data)

    mock_llm.analyze.assert_not_called()
    assert source.pop() is None


@pytest.mark.asyncio
async def test_galaxy_score_threshold_triggers_llm():
    """High galaxy_score alone should trigger LLM call."""
    mock_llm = AsyncMock()
    mock_llm.analyze = AsyncMock(return_value={"recommendation": "enter", "reasoning": "strong", "confidence": 0.9})

    source = LunarCrushSSESource(
        api_key="test",
        thresholds=SignalThresholds(coins=["BTC"], galaxy_score_min=65.0),
        llm_analyzer=mock_llm,
    )
    source._social_dominance_history["BTC"] = [2.0] * 7

    coin_data = _make_coin_data("BTC", galaxy_score=72.0, alt_rank=50, social_dominance=2.0)
    await source._process_coin(coin_data)

    mock_llm.analyze.assert_called_once()
    assert source.pop() is not None


@pytest.mark.asyncio
async def test_alt_rank_threshold_triggers_llm():
    """Low alt_rank alone should trigger LLM call."""
    mock_llm = AsyncMock()
    mock_llm.analyze = AsyncMock(return_value={"recommendation": "enter", "reasoning": "ranked", "confidence": 0.8})

    source = LunarCrushSSESource(
        api_key="test",
        thresholds=SignalThresholds(coins=["ETH"], alt_rank_max=20),
        llm_analyzer=mock_llm,
    )
    source._social_dominance_history["ETH"] = [1.5] * 7

    coin_data = _make_coin_data("ETH", galaxy_score=40.0, alt_rank=5, social_dominance=1.5)
    await source._process_coin(coin_data)

    mock_llm.analyze.assert_called_once()


@pytest.mark.asyncio
async def test_dominance_spike_triggers_llm():
    """Social dominance spike (ratio >= 2x) should trigger LLM."""
    mock_llm = AsyncMock()
    mock_llm.analyze = AsyncMock(return_value={"recommendation": "wait", "reasoning": "uncertain", "confidence": 0.5})

    source = LunarCrushSSESource(
        api_key="test",
        thresholds=SignalThresholds(coins=["BTC"], social_dominance_spike=2.0),
        llm_analyzer=mock_llm,
    )
    # Average = 2.0, new value = 5.0 → ratio = 2.5x
    source._social_dominance_history["BTC"] = [2.0] * 7

    coin_data = _make_coin_data("BTC", galaxy_score=40.0, alt_rank=50, social_dominance=5.0)
    await source._process_coin(coin_data)

    mock_llm.analyze.assert_called_once()


@pytest.mark.asyncio
async def test_llm_ignore_does_not_emit_event():
    """When LLM says ignore, no event should be emitted."""
    mock_llm = AsyncMock()
    mock_llm.analyze = AsyncMock(return_value={"recommendation": "ignore", "reasoning": "noise", "confidence": 0.1})

    source = LunarCrushSSESource(
        api_key="test",
        thresholds=SignalThresholds(coins=["BTC"]),
        llm_analyzer=mock_llm,
    )
    source._social_dominance_history["BTC"] = [2.0] * 7

    coin_data = _make_coin_data("BTC", galaxy_score=70.0)
    await source._process_coin(coin_data)

    mock_llm.analyze.assert_called_once()
    assert source.pop() is None


@pytest.mark.asyncio
async def test_unknown_coin_ignored():
    """Coins not in the thresholds.coins list should be silently skipped."""
    mock_llm = AsyncMock()
    mock_llm.analyze = AsyncMock()

    source = LunarCrushSSESource(
        api_key="test",
        thresholds=SignalThresholds(coins=["BTC"]),
        llm_analyzer=mock_llm,
    )

    coin_data = _make_coin_data("DOGE", galaxy_score=90.0, alt_rank=1)
    await source._process_coin(coin_data)

    mock_llm.analyze.assert_not_called()
    assert source.pop() is None


@pytest.mark.asyncio
async def test_emitted_event_fields():
    """Event fields should match the coin data from the SSE payload."""
    mock_llm = AsyncMock()
    mock_llm.analyze = AsyncMock(return_value={
        "recommendation": "enter", "reasoning": "confirmed breakout", "confidence": 0.92
    })

    source = LunarCrushSSESource(
        api_key="test",
        thresholds=SignalThresholds(coins=["ETH"]),
        llm_analyzer=mock_llm,
    )
    source._social_dominance_history["ETH"] = [1.0] * 7

    coin_data = _make_coin_data("ETH", galaxy_score=75.0, alt_rank=3, social_dominance=1.5,
                                price=3500.0, price_change_24h=5.5)
    await source._process_coin(coin_data)

    event = source.pop()
    assert event is not None
    assert isinstance(event, LunarCrushSignalEvent)
    assert event.coin == "ETH"
    assert event.galaxy_score == 75.0
    assert event.price == 3500.0
    assert event.price_change_24h == 5.5
    assert event.recommendation == "enter"
    assert event.confidence == 0.92
