import json
import logging
import os
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

PROMPT_TEMPLATE = """{coin} social signal detected on LunarCrush:
- Galaxy Score: {galaxy_score:.1f} (threshold: >{galaxy_score_min})
- Social dominance: {social_dominance_ratio:.1f}x above 7-day average
- AltRank: {alt_rank}
- Price: ${price:.4f} ({price_change_24h:+.1f}% in 24h)

Is this a genuine breakout signal or social noise?
Consider: macro context, whether price confirms the social move, typical false positive patterns.

Respond ONLY with valid JSON:
{{"recommendation": "enter" or "wait" or "ignore", "reasoning": "one sentence max", "confidence": 0.0}}"""


class LLMAnalyzer:
    def __init__(
        self,
        api_base: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_base = api_base or os.getenv("LLM_API_BASE", "https://openrouter.ai/api/v1")
        self.api_key = api_key or os.getenv("LLM_API_KEY", "")
        self.model = model or os.getenv("LLM_MODEL", "anthropic/claude-haiku-4-5")

    async def analyze(self, data: dict, thresholds: "SignalThresholds") -> dict:
        prompt = PROMPT_TEMPLATE.format(
            coin=data["coin"],
            galaxy_score=data["galaxy_score"],
            galaxy_score_min=thresholds.galaxy_score_min,
            social_dominance_ratio=data.get("social_dominance_ratio", 1.0),
            alt_rank=data["alt_rank"],
            price=data["price"],
            price_change_24h=data.get("price_change_24h", 0.0),
        )
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_base}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 150,
                    },
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    result = await resp.json()
                    content = result["choices"][0]["message"]["content"].strip()
                    if content.startswith("```"):
                        content = content.split("```")[1]
                        if content.startswith("json"):
                            content = content[4:]
                    return json.loads(content.strip())
        except Exception as e:
            logger.warning(f"LLM analysis failed: {e}")
            return {"recommendation": "wait", "reasoning": "LLM unavailable", "confidence": 0.0}
