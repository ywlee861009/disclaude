"""
disclaude — Discord + Claude Code 연동 봇
==========================================
디스코드 슬래시 명령어를 통해 Claude Code CLI를 원격으로 제어하는 봇.

주요 기능:
  /ping           : 봇 상태 확인
  /ask            : Claude에게 일반 질문
  /continue_chat  : 이전 대화 이어서 질문
  /code           : 지정 프로젝트의 코드 수정 지시
  /gen-pr         : 브랜치 생성 → 코드 수정 → PR 자동 생성

보안 기능:
  - 허용된 단일 사용자 접근 제어
  - 사용자별 Rate Limiting (분당 요청 수 제한)
  - 브랜치 이름 화이트리스트 검증
  - 민감 파일 접근 차단 (시스템 프롬프트 주입)
  - 응답 내 민감 정보 필터링
  - 전체 명령어 감사 로그 기록
"""

import re
import os
import sys
import time
import logging
import asyncio
from collections import defaultdict

import discord
from discord import app_commands
from dotenv import load_dotenv

# ──────────────────────────────────────────────
# 로깅 설정
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("disclaude")

# 감사 로그 전용 로거 — 누가 어떤 명령어를 실행했는지 기록
audit_logger = logging.getLogger("disclaude.audit")
_audit_handler = logging.FileHandler("audit.log", encoding="utf-8")
_audit_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%Y-%m-%d %H:%M:%S"))
audit_logger.addHandler(_audit_handler)
audit_logger.setLevel(logging.INFO)

# ──────────────────────────────────────────────
# 환경변수 로드 및 검증
# ──────────────────────────────────────────────
load_dotenv()

# 필수 환경변수 목록 — 하나라도 누락되면 봇이 시작되지 않음
REQUIRED_ENV = {
    "DISCORD_TOKEN": "디스코드 봇 토큰",
    "ALLOWED_USER_ID": "허용된 사용자의 디스코드 ID",
    "TARGET_PROJECT_PATH": "코드 수정 대상 프로젝트 경로",
}

_missing = [f"  - {key} ({desc})" for key, desc in REQUIRED_ENV.items() if not os.getenv(key)]
if _missing:
    logger.error("필수 환경변수가 설정되지 않았습니다:\n%s", "\n".join(_missing))
    sys.exit(1)

DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN")
CLAUDE_PATH: str = os.getenv("CLAUDE_PATH", "claude")
TARGET_PROJECT: str = os.getenv("TARGET_PROJECT_PATH")

# 허용된 단일 사용자 ID
ALLOWED_USER_ID: int = int(os.getenv("ALLOWED_USER_ID"))

# 분당 최대 요청 수 (Rate Limiting)
RATE_LIMIT_PER_MINUTE: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "10"))

# Claude CLI 실행 시 최대 대기 시간 (초)
CLAUDE_TIMEOUT = 300

# 디스코드 메시지 최대 길이 (여유분 포함)
DISCORD_MAX_LENGTH = 1900

# ──────────────────────────────────────────────
# 보안: 브랜치 이름 검증
# ──────────────────────────────────────────────
# 허용 패턴: 영문, 숫자, 하이픈, 슬래시, 언더스코어만 허용
# 예: feat/login-page, fix/bug-123, refactor_auth
BRANCH_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9/_-]{0,99}$")

# ──────────────────────────────────────────────
# 보안: 민감 파일 패턴
# ──────────────────────────────────────────────
# Claude 응답에서 이 패턴이 발견되면 마스킹 처리
SENSITIVE_PATTERNS = [
    # 환경변수 / 토큰 값 패턴 (긴 영숫자 문자열)
    re.compile(r"(DISCORD_TOKEN|TOKEN|SECRET|PASSWORD|API_KEY|PRIVATE_KEY)\s*=\s*\S+", re.IGNORECASE),
    # .env 파일 내용이 통째로 노출되는 경우
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

# ──────────────────────────────────────────────
# Rate Limiter
# ──────────────────────────────────────────────
class RateLimiter:
    """사용자별 분당 요청 수를 제한하는 Rate Limiter."""

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


rate_limiter = RateLimiter(RATE_LIMIT_PER_MINUTE)

# ──────────────────────────────────────────────
# 디스코드 클라이언트 초기화
# ──────────────────────────────────────────────
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# 동시에 여러 Claude 프로세스가 실행되지 않도록 하는 락
task_lock = asyncio.Lock()

# 슬래시 명령어 동기화 여부 (최초 1회만 sync)
_commands_synced = False


# ──────────────────────────────────────────────
# 보안 유틸리티 함수
# ──────────────────────────────────────────────
def is_allowed(interaction: discord.Interaction) -> bool:
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


# ──────────────────────────────────────────────
# 핵심 유틸리티 함수
# ──────────────────────────────────────────────
async def run_claude(args: list[str], cwd: str | None = None) -> str:
    """
    Claude Code CLI를 서브프로세스로 실행하고 결과를 반환한다.

    Args:
        args: Claude CLI에 전달할 인자 리스트 (예: ["-p", "질문 내용"])
        cwd:  작업 디렉토리. None이면 현재 디렉토리 사용.

    Returns:
        Claude CLI의 stdout 출력 (민감 정보 마스킹 적용됨)

    Raises:
        Exception: 타임아웃(5분 초과) 또는 비정상 종료 시
    """
    logger.info("Claude 실행: args=%s, cwd=%s", args, cwd)

    proc = await asyncio.create_subprocess_exec(
        CLAUDE_PATH, *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        # FORCE_COLOR=0 → ANSI 색상 코드 제거 (디스코드 출력용)
        env={**os.environ, "FORCE_COLOR": "0"},
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=CLAUDE_TIMEOUT
        )
    except asyncio.TimeoutError:
        proc.kill()
        logger.error("Claude 프로세스 타임아웃 (%d초 초과)", CLAUDE_TIMEOUT)
        raise Exception(f"타임아웃: {CLAUDE_TIMEOUT}초 초과")

    output = stdout.decode().strip()
    if proc.returncode != 0:
        error_msg = stderr.decode().strip() or f"exit code {proc.returncode}"
        logger.error("Claude 실행 실패: %s", error_msg)
        raise Exception(error_msg)

    # 응답에서 민감 정보 마스킹
    output = sanitize_output(output)

    logger.info("Claude 응답 완료 (길이: %d자)", len(output))
    return output


async def send_long(interaction: discord.Interaction, text: str, prefix: str = "") -> None:
    """
    긴 텍스트를 디스코드 메시지 길이 제한(2000자)에 맞춰 분할 전송한다.

    Args:
        interaction: 디스코드 인터랙션 객체
        text:        전송할 텍스트
        prefix:      첫 번째 메시지 앞에 붙일 접두사 (예: "**Claude 응답:**")
    """
    # 텍스트가 짧으면 한 번에 전송
    content = f"{prefix}\n```\n{text}\n```" if prefix else f"```\n{text}\n```"
    if len(content) <= 2000:
        await interaction.followup.send(content)
        return

    # 긴 텍스트는 DISCORD_MAX_LENGTH 단위로 분할
    chunks: list[str] = []
    while text:
        chunks.append(text[:DISCORD_MAX_LENGTH])
        text = text[DISCORD_MAX_LENGTH:]

    # 첫 번째 청크에만 prefix 포함
    await interaction.followup.send(f"{prefix}\n```\n{chunks[0]}\n```")
    for chunk in chunks[1:]:
        await interaction.followup.send(f"```\n{chunk}\n```")


async def handle_claude_command(
    interaction: discord.Interaction,
    args: list[str],
    prefix: str,
    cwd: str | None = None,
    command_name: str = "unknown",
    detail: str = "",
) -> None:
    """
    Claude 명령어의 공통 실행 흐름을 처리한다.
    권한 확인 → Rate Limit → 감사 로그 → defer → 락 획득 → Claude 실행 → 응답 전송

    Args:
        interaction:  디스코드 인터랙션 객체
        args:         Claude CLI 인자 리스트
        prefix:       응답 메시지 접두사
        cwd:          작업 디렉토리 (선택)
        command_name: 감사 로그에 기록할 명령어 이름
        detail:       감사 로그에 추가할 상세 내용
    """
    # 1단계: 권한 확인
    if not is_allowed(interaction):
        logger.warning(
            "권한 없는 접근 시도: user=%s(%s)",
            interaction.user.name, interaction.user.id,
        )
        await interaction.response.send_message("권한이 없습니다.", ephemeral=True)
        return

    # 2단계: Rate Limit 확인
    if not rate_limiter.is_allowed(interaction.user.id):
        remaining_msg = f"요청 한도 초과 (분당 {RATE_LIMIT_PER_MINUTE}회). 잠시 후 다시 시도해주세요."
        await interaction.response.send_message(remaining_msg, ephemeral=True)
        return

    # 3단계: 감사 로그 기록
    audit_log(interaction.user, command_name, detail)

    await interaction.response.defer()

    async with task_lock:
        try:
            result = await run_claude(args, cwd=cwd)
            await send_long(interaction, result, prefix)
        except Exception as e:
            logger.exception("명령어 처리 중 오류 발생")
            await interaction.followup.send(f"오류 발생:\n```\n{str(e)[:1800]}\n```")


# ──────────────────────────────────────────────
# 슬래시 명령어 정의
# ──────────────────────────────────────────────
@tree.command(name="ping", description="봇 상태 확인")
async def ping(interaction: discord.Interaction):
    """봇이 살아있는지 확인하는 헬스체크 명령어."""
    await interaction.response.send_message("Pong! 봇이 정상 작동 중입니다.")


@tree.command(name="ask", description="Claude Code에게 질문하기")
@app_commands.describe(prompt="질문 내용")
async def ask(interaction: discord.Interaction, prompt: str):
    """Claude에게 일반적인 질문을 던진다. 프로젝트 컨텍스트 없이 독립 실행."""
    await handle_claude_command(
        interaction,
        args=["-p", prompt, "--output-format", "text"],
        prefix="**Claude 응답:**",
        command_name="/ask",
        detail=prompt[:100],
    )


@tree.command(name="continue_chat", description="이전 대화 이어서 질문")
@app_commands.describe(prompt="이어서 할 질문")
async def continue_chat(interaction: discord.Interaction, prompt: str):
    """직전 Claude 대화의 컨텍스트를 이어받아 후속 질문을 한다."""
    await handle_claude_command(
        interaction,
        args=["-p", prompt, "--continue", "--output-format", "text"],
        prefix="**Claude 응답 (이어서):**",
        command_name="/continue_chat",
        detail=prompt[:100],
    )


@tree.command(name="code", description="프로젝트 코드 수정 지시")
@app_commands.describe(instruction="수정 지시 내용")
async def code(interaction: discord.Interaction, instruction: str):
    """
    TARGET_PROJECT 경로에서 Claude에게 코드 수정을 지시한다.
    보안 프롬프트가 자동으로 앞에 주입되어 민감 파일 접근을 차단한다.
    """
    # 보안 프롬프트를 사용자 지시 앞에 주입
    secured_instruction = SECURITY_PROMPT + instruction

    await handle_claude_command(
        interaction,
        args=[
            "-p", secured_instruction,
            "--output-format", "text",
            "--allowedTools", "Edit,Write,Read,Glob,Grep,Bash",
        ],
        prefix="**코드 수정 결과:**",
        cwd=TARGET_PROJECT,
        command_name="/code",
        detail=instruction[:100],
    )


@tree.command(name="gen-pr", description="브랜치 생성 → 코드 수정 → PR 자동 생성")
@app_commands.describe(branch="브랜치 이름", instruction="수정 지시 내용")
async def gen_pr(interaction: discord.Interaction, branch: str, instruction: str):
    """
    자동으로 브랜치를 생성하고, 코드를 수정한 뒤, PR을 만들어준다.
    브랜치 이름은 화이트리스트 패턴으로 검증된다.
    """
    # 1단계: 권한 확인 (handle_claude_command 전에 별도 검증이 필요)
    if not is_allowed(interaction):
        await interaction.response.send_message("권한이 없습니다.", ephemeral=True)
        return

    # 2단계: 브랜치 이름 검증 — 인젝션 공격 방지
    error = validate_branch_name(branch)
    if error:
        await interaction.response.send_message(f"입력 오류:\n{error}", ephemeral=True)
        return

    # 보안 프롬프트 + 구조화된 지시
    full_prompt = (
        f"{SECURITY_PROMPT}"
        f"다음 작업을 순서대로 수행해줘:\n"
        f"1. git checkout -b {branch}\n"
        f"2. {instruction}\n"
        f"3. 변경사항을 커밋해\n"
        f"4. git push -u origin {branch}\n"
        f"5. gh pr create --fill\n"
        f"마지막에 PR URL을 출력해줘."
    )
    await handle_claude_command(
        interaction,
        args=[
            "-p", full_prompt,
            "--output-format", "text",
            "--allowedTools", "Edit,Write,Read,Glob,Grep,Bash",
        ],
        prefix="**PR 생성 결과:**",
        cwd=TARGET_PROJECT,
        command_name="/gen-pr",
        detail=f"branch={branch} | {instruction[:80]}",
    )


# ──────────────────────────────────────────────
# 이벤트 핸들러
# ──────────────────────────────────────────────
@client.event
async def on_ready():
    """봇 로그인 완료 시 호출. 슬래시 명령어를 최초 1회만 동기화한다."""
    global _commands_synced
    if not _commands_synced:
        await tree.sync()
        _commands_synced = True
        logger.info("슬래시 명령어 동기화 완료")
    logger.info("봇 로그인 완료: %s (ID: %s)", client.user, client.user.id)


# ──────────────────────────────────────────────
# 엔트리포인트
# ──────────────────────────────────────────────
if __name__ == "__main__":
    logger.info("disclaude 봇을 시작합니다...")
    client.run(DISCORD_TOKEN, log_handler=None)
