"""
commands — 디스코드 슬래시 명령어 정의
=======================================
각 명령어의 비즈니스 로직을 정의한다.
공통 흐름(권한→Rate Limit→감사→실행)은 handle_claude_command에 위임.
"""

import logging
import asyncio

import discord
from discord import app_commands

from .config import TARGET_PROJECT, RATE_LIMIT_PER_MINUTE, SECURITY_PROMPT
from .security import is_allowed_user, validate_branch_name, audit_log, RateLimiter
from .claude_runner import run_claude, send_long

logger = logging.getLogger("disclaude")

# 동시에 여러 Claude 프로세스가 실행되지 않도록 하는 락
task_lock = asyncio.Lock()


def register_commands(tree: app_commands.CommandTree, rate_limiter: RateLimiter) -> None:
    """
    슬래시 명령어들을 CommandTree에 등록한다.

    Args:
        tree:         디스코드 CommandTree 객체
        rate_limiter: 요청 제한기 인스턴스
    """

    # ──────────────────────────────────────────
    # 공통 명령어 처리 흐름
    # ──────────────────────────────────────────
    async def handle_claude_command(
        interaction: discord.Interaction,
        args: list[str],
        prefix: str,
        cwd: str | None = None,
        command_name: str = "unknown",
        detail: str = "",
    ) -> None:
        """
        권한 확인 → Rate Limit → 감사 로그 → defer → 락 획득 → Claude 실행 → 응답 전송
        """
        # 1단계: 권한 확인
        if not is_allowed_user(interaction):
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

    # ──────────────────────────────────────────
    # /ping — 봇 상태 확인
    # ──────────────────────────────────────────
    @tree.command(name="ping", description="봇 상태 확인")
    async def ping(interaction: discord.Interaction):
        """봇이 살아있는지 확인하는 헬스체크 명령어."""
        await interaction.response.send_message("Pong! 봇이 정상 작동 중입니다.")

    # ──────────────────────────────────────────
    # /ask — Claude에게 일반 질문
    # ──────────────────────────────────────────
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

    # ──────────────────────────────────────────
    # /continue_chat — 이전 대화 이어서 질문
    # ──────────────────────────────────────────
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

    # ──────────────────────────────────────────
    # /code — 프로젝트 코드 수정 지시
    # ──────────────────────────────────────────
    @tree.command(name="code", description="프로젝트 코드 수정 지시")
    @app_commands.describe(instruction="수정 지시 내용")
    async def code(interaction: discord.Interaction, instruction: str):
        """
        TARGET_PROJECT 경로에서 Claude에게 코드 수정을 지시한다.
        보안 프롬프트가 자동으로 앞에 주입되어 민감 파일 접근을 차단한다.
        """
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

    # ──────────────────────────────────────────
    # /gen-pr — 브랜치 생성 + 코드 수정 + PR 생성
    # ──────────────────────────────────────────
    @tree.command(name="gen-pr", description="브랜치 생성 → 코드 수정 → PR 자동 생성")
    @app_commands.describe(branch="브랜치 이름", instruction="수정 지시 내용")
    async def gen_pr(interaction: discord.Interaction, branch: str, instruction: str):
        """
        자동으로 브랜치를 생성하고, 코드를 수정한 뒤, PR을 만들어준다.
        브랜치 이름은 화이트리스트 패턴으로 검증된다.
        """
        # 권한 확인 (브랜치 검증을 위해 handle_claude_command 전에 수행)
        if not is_allowed_user(interaction):
            await interaction.response.send_message("권한이 없습니다.", ephemeral=True)
            return

        # 브랜치 이름 검증 — 인젝션 공격 방지
        error = validate_branch_name(branch)
        if error:
            await interaction.response.send_message(f"입력 오류:\n{error}", ephemeral=True)
            return

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
