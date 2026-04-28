from typing import Any

from .base import sleep_ms_ranged


class FastEnricher:
    def enrich(self, analysis: dict[str, Any]) -> dict[str, Any]:
        sleep_ms_ranged(100, 250, label="Enrich", variant="fast")
        n = len(analysis.get("entities") or [])
        return {
            "metadata": {
                "enriched": True,
                "entity_count": n,
            },
        }


class SlowEnricher:
    def enrich(self, analysis: dict[str, Any]) -> dict[str, Any]:
        sleep_ms_ranged(300, 500, label="Enrich", variant="slow")
        n = len(analysis.get("entities") or [])
        return {
            "metadata": {
                "enriched": True,
                "entity_count": n,
                "variant": "slow",
            },
        }
