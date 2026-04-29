import re
from typing import Any

from .base import sleep_ms_ranged


class _BaseAnalyzer:
    def _common(self, text: str) -> dict[str, Any]:
        words = re.findall(r"\w+", (text or "").lower())
        return {
            "entities": list({w for w in words if len(w) > 2})[:10],
            "categories": (["text"] if text else []),
        }


class FastMockAnalyzer(_BaseAnalyzer):
    def analyze(self, text: str) -> dict[str, Any]:
        sleep_ms_ranged(100, 200, label="Analyze", variant="fast")
        out = self._common(text)
        return {"variant": "fast", **out}


class SlowMockAnalyzer(_BaseAnalyzer):
    def analyze(self, text: str) -> dict[str, Any]:
        sleep_ms_ranged(300, 500, label="Analyze", variant="slow")
        out = self._common(text)
        return {"variant": "slow", "entities": out["entities"][:5], "categories": out["categories"]}
