import hashlib
import re

from .base import sleep_ms_ranged


class FastExtractor:
    def extract(self, raw_content: str) -> str:
        sleep_ms_ranged(100, 200, label="Extract", variant="fast")
        text = re.sub(r"\s+", " ", (raw_content or "").strip())
        if not text:
            return "[empty]"
        return f"extracted:{text[:200]}"


class SlowExtractor:
    def extract(self, raw_content: str) -> str:
        sleep_ms_ranged(300, 500, label="Extract", variant="slow")
        text = re.sub(r"\s+", " ", (raw_content or "").strip())
        if not text:
            return "[empty]"
        h = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:8]
        return f"extracted:sha8={h} body={text[:200]}"
