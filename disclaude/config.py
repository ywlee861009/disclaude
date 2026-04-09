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
# Claude CLI 실행 시 최대 대기 시간 (초) — 명령어별 기본값
CLAUDE_TIMEOUT = 300

# 명령어별 타임아웃 (초)
COMMAND_TIMEOUTS: dict[str, int] = {
    "/ask": 60,
    "/continue_chat": 60,
    "/code": 300,
    "/commit-pr": 600,
}

# Claude 실행 중 사용자에게 보낼 진행 알림 (경과 초, 메시지)
PROGRESS_NOTIFICATIONS: list[tuple[int, str]] = [
    (30, "⏳ 아직 처리 중입니다... (30초 경과)"),
    (60, "⏳ 처리 중입니다... (1분 경과)"),
    (120, "⏳ 처리가 길어지고 있습니다... (2분 경과)"),
    (240, "⏳ 거의 완료될 예정입니다... (4분 경과)"),
    (480, "⏳ 오래 걸리고 있습니다... (8분 경과)"),
]

# 디스코드 메시지 최대 길이 (여유분 포함)
DISCORD_MAX_LENGTH = 1900

# 브랜치 이름 허용 패턴: 영문, 숫자, 하이픈, 슬래시, 언더스코어
# 예: feat/login-page, fix/bug-123, refactor_auth
BRANCH_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9/_-]{0,99}$")

# Claude 응답에서 마스킹할 민감 정보 패턴
SENSITIVE_PATTERNS = [
    # 환경변수 / 토큰 값 패턴 (KEY=VALUE 형식)
    re.compile(r"(DISCORD_TOKEN|TOKEN|SECRET|PASSWORD|API_KEY|PRIVATE_KEY|DATABASE_URL|DB_PASSWORD)\s*=\s*\S+", re.IGNORECASE),
    # GitHub 토큰
    re.compile(r"(ghp_|gho_|github_pat_)[a-zA-Z0-9_-]{20,}"),
    # Slack 토큰
    re.compile(r"xox[bpas]-[a-zA-Z0-9-]{10,}"),
    # OpenAI / Anthropic API 키
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    # AWS 키
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"aws_secret_access_key\s*=\s*\S+", re.IGNORECASE),
    # Bearer 토큰
    re.compile(r"Bearer\s+[a-zA-Z0-9._-]{20,}", re.IGNORECASE),
    # 일반적인 시크릿 형식 (따옴표 안의 긴 영숫자 문자열이 KEY 옆에 있는 경우)
    re.compile(r"""(?:secret|token|password|api_key|apikey)\s*[:=]\s*["'][^"']{8,}["']""", re.IGNORECASE),
]

# /code 명령어에 허용할 도구 (Bash 제외 — 셸 명령 실행 차단)
# 프롬프트 인젝션으로 SECURITY_PROMPT를 우회해도 파괴적 명령 실행 불가
CODE_ALLOWED_TOOLS = "Edit,Write,Read,Glob,Grep"

# /gen-pr 명령어에 허용할 도구 (git 명령 실행을 위해 Bash 포함)
PR_ALLOWED_TOOLS = "Edit,Write,Read,Glob,Grep,Bash"

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
