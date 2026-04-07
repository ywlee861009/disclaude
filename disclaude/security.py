"""
security — 보안 관련 유틸리티
==============================
접근 제어, Rate Limiting, 입력 검증, 출력 마스킹, 감사 로그를 담당한다.
"""

import time
import logging
from collections import defaultdict

import discord

from .config import (
    ALLOWED_USER_ID,
    BRANCH_NAME_PATTERN,
    SENSITIVE_PATTERNS,
)

# ──────────────────────────────────────────────
# 감사 로그 설정
# ──────────────────────────────────────────────
audit_logger = logging.getLogger("disclaude.audit")
_audit_handler = logging.FileHandler("audit.log", encoding="utf-8")
_audit_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%Y-%m-%d %H:%M:%S"))
audit_logger.addHandler(_audit_handler)
audit_logger.setLevel(logging.INFO)


# ──────────────────────────────────────────────
# Rate Limiter
# ──────────────────────────────────────────────
class RateLimiter:
    """사용자별 분당 요청 수를 제한하는 슬라이딩 윈도우 Rate Limiter."""

    def __init__(self, max_per_minute: int):
        self.max_per_minute = max_per_minute
        # 사용자 ID → 요청 타임스탬프 리스트
        self._requests: dict[int, list[float]] = defaultdict(list)

    def is_allowed(self, user_id: int) -> bool:
        """요청이 허용되는지 확인하고, 허용되면 기록한다."""
        now = time.time()
        window_start = now - 60  # 최근 1분

        # 만료된 요청 제거
        self._requests[user_id] = [
            t for t in self._requests[user_id] if t > window_start
        ]

        if len(self._requests[user_id]) >= self.max_per_minute:
            return False

        self._requests[user_id].append(now)
        return True

    def remaining(self, user_id: int) -> int:
        """남은 요청 횟수를 반환한다."""
        now = time.time()
        window_start = now - 60
        recent = [t for t in self._requests[user_id] if t > window_start]
        return max(0, self.max_per_minute - len(recent))


# ──────────────────────────────────────────────
# 검증 및 필터링 함수
# ──────────────────────────────────────────────
def is_allowed_user(interaction: discord.Interaction) -> bool:
    """허용된 사용자인지 확인한다."""
    return interaction.user.id == ALLOWED_USER_ID


def validate_branch_name(branch: str) -> str | None:
    """
    브랜치 이름이 안전한지 검증한다.

    Returns:
        None이면 유효, 문자열이면 에러 메시지
    """
    if not BRANCH_NAME_PATTERN.match(branch):
        return (
            "브랜치 이름이 유효하지 않습니다.\n"
            "허용: 영문, 숫자, 하이픈(-), 슬래시(/), 언더스코어(_)\n"
            "예시: `feat/login-page`, `fix/bug-123`"
        )
    # 경로 탈출 시도 차단
    if ".." in branch:
        return "브랜치 이름에 `..`은 사용할 수 없습니다."
    return None


def sanitize_output(text: str) -> str:
    """
    Claude 응답에서 민감한 정보를 마스킹한다.
    토큰, 비밀번호 등이 실수로 포함된 경우 [REDACTED]로 대체.
    """
    sanitized = text
    for pattern in SENSITIVE_PATTERNS:
        sanitized = pattern.sub("[REDACTED]", sanitized)
    return sanitized


def audit_log(user: discord.User, command: str, detail: str = "") -> None:
    """감사 로그에 명령어 실행 기록을 남긴다."""
    detail_str = f" | {detail}" if detail else ""
    audit_logger.info(
        "user=%s(%s) command=%s%s",
        user.name, user.id, command, detail_str,
    )
