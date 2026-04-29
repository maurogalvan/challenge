from __future__ import annotations

import logging
import random
import time
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


class ProviderError(Exception):
    """Error controlado al ejecutar un proveedor mock."""


@runtime_checkable
class Extractor(Protocol):
    def extract(self, raw_content: str) -> str: ...


@runtime_checkable
class Analyzer(Protocol):
    def analyze(self, text: str) -> dict[str, Any]: ...


@runtime_checkable
class Enricher(Protocol):
    def enrich(self, analysis: dict[str, Any]) -> dict[str, Any]: ...


def sleep_ms_ranged(
    low_ms: int, high_ms: int, *, label: str = "provider", variant: str = ""
) -> None:
    if high_ms < low_ms:
        low_ms, high_ms = high_ms, low_ms
    ms = random.uniform(low_ms, high_ms)
    extra = f" ({variant})" if variant else ""
    logger.info(
        "Mock latency %s%s sample=%.1fms range=%d-%dms",
        label,
        extra,
        ms,
        low_ms,
        high_ms,
    )
    time.sleep(ms / 1000.0)
