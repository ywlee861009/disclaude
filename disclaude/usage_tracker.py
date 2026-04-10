"""
usage_tracker — Claude API 사용량 누적 추적
============================================
각 Claude CLI 호출의 토큰/비용 정보를 JSON 파일에 누적 저장한다.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("disclaude")

_USAGE_FILE = Path("usage.json")


class UsageTracker:
    """토큰 사용량과 비용을 누적 추적한다."""

    def __init__(self):
        self._data = self._load()

    def _load(self) -> dict:
        try:
            return json.loads(_USAGE_FILE.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {"total": self._empty(), "daily": {}}

    def _save(self) -> None:
        _USAGE_FILE.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _empty() -> dict:
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
            "cost_usd": 0.0,
            "requests": 0,
        }

    def record(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int,
        cache_creation_tokens: int,
        cost_usd: float,
    ) -> None:
        today = datetime.now().strftime("%Y-%m-%d")

        for bucket in [self._data["total"], self._data["daily"].setdefault(today, self._empty())]:
            bucket["input_tokens"] += input_tokens
            bucket["output_tokens"] += output_tokens
            bucket["cache_read_tokens"] += cache_read_tokens
            bucket["cache_creation_tokens"] += cache_creation_tokens
            bucket["cost_usd"] += cost_usd
            bucket["requests"] += 1

        self._save()

    def get_today(self) -> dict:
        today = datetime.now().strftime("%Y-%m-%d")
        return self._data["daily"].get(today, self._empty())

    def get_total(self) -> dict:
        return self._data["total"]


usage_tracker = UsageTracker()
