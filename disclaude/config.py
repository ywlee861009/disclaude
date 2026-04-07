"""
config — 환경변수 로드 및 상수 정의
====================================
봇 실행에 필요한 모든 설정값을 한 곳에서 관리한다.
필수 환경변수가 누락되면 시작 시점에 에러를 발생시킨다.
"""

import os
import re
import sys
import logging

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("disclaude")

# ──────────────────────────────────────────────
# 필수 환경변수 검증
# ──────────────────────────────────────────────
REQUIRED_ENV = {
    "DISCORD_TOKEN": "디스코드 봇 토큰",
    "ALLOWED_USER_ID": "허용된 사용자의 디스코드 ID",
    "TARGET_PROJECT_PATH": "코드 수정 대상 프로젝트 경로",
}

_missing = [f"  - {key} ({desc})" for key, desc in REQUIRED_ENV.items() if not os.getenv(key)]
if _missing:
    logger.error("필수 환경변수가 설정되지 않았습니다:\n%s", "\n".join(_missing))
    sys.exit(1)

# ──────────────────────────────────────────────
# 환경변수 로드
# ──────────────────────────────────────────────
DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN")
CLAUDE_PATH: str = os.getenv("CLAUDE_PATH", "claude")
TARGET_PROJECT: str = os.getenv("TARGET_PROJECT_PATH")
ALLOWED_USER_ID: int = int(os.getenv("ALLOWED_USER_ID"))
RATE_LIMIT_PER_MINUTE: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "10"))

# ──────────────────────────────────────────────
# 상수
# ──────────────────────────────────────────────
# Claude CLI 실행 시 최대 대기 시간 (초)
CLAUDE_TIMEOUT = 300

# 디스코드 메시지 최대 길이 (여유분 포함)
DISCORD_MAX_LENGTH = 1900

# 브랜치 이름 허용 패턴: 영문, 숫자, 하이픈, 슬래시, 언더스코어
# 예: feat/login-page, fix/bug-123, refactor_auth
BRANCH_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9/_-]{0,99}$")

# Claude 응답에서 마스킹할 민감 정보 패턴
SENSITIVE_PATTERNS = [
    # 환경변수 / 토큰 값 패턴
    re.compile(r"(DISCORD_TOKEN|TOKEN|SECRET|PASSWORD|API_KEY|PRIVATE_KEY)\s*=\s*\S+", re.IGNORECASE),
    # GitHub, Slack, OpenAI 등의 토큰 형식
    re.compile(r"(ghp_|gho_|github_pat_|xoxb-|xoxp-|sk-)[a-zA-Z0-9_-]{20,}", re.IGNORECASE),
]

# Claude에게 주입할 보안 시스템 프롬프트
# 민감 파일 접근을 차단하고, 위험한 명령어 실행을 방지
SECURITY_PROMPT = (
    "중요 보안 규칙 (반드시 준수):\n"
    "1. 다음 파일은 절대 읽거나 내용을 출력하지 마: .env, .env.*, *.pem, *.key, id_rsa*, credentials*, secrets*, token*\n"
    "2. 환경변수 값(TOKEN, SECRET, PASSWORD, API_KEY 등)을 절대 출력하지 마\n"
    "3. rm -rf, 파일 삭제, 디스크 포맷 등 파괴적 명령어를 실행하지 마\n"
    "4. 프로젝트 디렉토리 바깥의 파일을 읽거나 수정하지 마\n"
    "5. curl, wget 등으로 외부 서버에 데이터를 전송하지 마\n"
    "---\n"
)
