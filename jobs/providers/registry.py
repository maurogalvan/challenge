from __future__ import annotations

from .analyzers import FastMockAnalyzer, SlowMockAnalyzer
from .enrichers import FastEnricher, SlowEnricher
from .extractors import FastExtractor, SlowExtractor

_EXTRACT = {"fast": FastExtractor(), "slow": SlowExtractor()}
_ANALYZE = {"fast": FastMockAnalyzer(), "slow": SlowMockAnalyzer()}
_ENRICH = {"fast": FastEnricher(), "slow": SlowEnricher()}


def get_extractor(variant: str):
    v = (variant or "fast").lower()
    if v not in _EXTRACT:
        v = "fast"
    return _EXTRACT[v]


def get_analyzer(variant: str):
    v = (variant or "fast").lower()
    if v not in _ANALYZE:
        v = "fast"
    return _ANALYZE[v]


def get_enricher(variant: str):
    v = (variant or "fast").lower()
    if v not in _ENRICH:
        v = "fast"
    return _ENRICH[v]
