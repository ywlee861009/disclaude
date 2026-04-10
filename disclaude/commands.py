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

from .config import TARGET_PROJECT, RATE_LIMIT_PER_MINUTE, SECURITY_PROMPT, CODE_ALLOWED_TOOLS, PR_ALLOWED_TOOLS, COMMAND_TIMEOUTS, CLAUDE_TIMEOUT
from .security import is_allowed_user, validate_branch_name, audit_log, RateLimiter
from .claude_runner import run_claude, send_long, _send_progress
from .usage_tracker import usage_tracker

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

        if task_lock.locked():
            await interaction.followup.send("⏳ 앞선 요청을 처리 중입니다. 완료되면 자동으로 실행됩니다...")
            logger.info("Lock 대기 중: user=%s, command=%s", interaction.user.name, command_name)

        async with task_lock:
            timeout = COMMAND_TIMEOUTS.get(command_name, CLAUDE_TIMEOUT)
            progress_task = asyncio.create_task(_send_progress(interaction, timeout))
            try:
                result = await run_claude(args, cwd=cwd, command_name=command_name)
                await send_long(interaction, result, prefix)
            except Exception as e:
                logger.exception("명령어 처리 중 오류 발생")
                error_text = str(e)[:1800]
                if "타임아웃" in str(e):
                    error_text += f"\n\n💡 이 명령어의 타임아웃은 {timeout}초입니다. 더 짧은 요청으로 나눠 시도해보세요."
                try:
                    await interaction.followup.send(f"오류 발생:\n```\n{error_text}\n```")
                except discord.HTTPException:
                    # Gateway 재연결 등으로 interaction이 만료된 경우
                    logger.warning("interaction 만료로 에러 응답 전송 실패 (command=%s)", command_name)
                    try:
                        await interaction.channel.send(
                            f"⚠️ **{interaction.user.mention}** {command_name} 처리 중 오류가 발생했습니다:\n```\n{error_text[:1500]}\n```"
                        )
                    except discord.HTTPException:
                        logger.error("채널 메시지 전송도 실패 (command=%s)", command_name)
            finally:
                progress_task.cancel()

    # ──────────────────────────────────────────
    # /usage — 토큰 사용량 및 비용 통계
    # ──────────────────────────────────────────
    def _format_tokens(n: int) -> str:
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n / 1_000:.1f}K"
        return str(n)

    def _format_usage(label: str, data: dict) -> str:
        inp = data["input_tokens"]
        out = data["output_tokens"]
        cache_read = data["cache_read_tokens"]
        cache_create = data["cache_creation_tokens"]
        cost = data["cost_usd"]
        reqs = data["requests"]
        lines = [
            f"**{label}** — {reqs}회 요청, ${cost:.4f}",
            f"  input: {_format_tokens(inp)} / output: {_format_tokens(out)}",
            f"  cache read: {_format_tokens(cache_read)} / cache write: {_format_tokens(cache_create)}",
        ]
        return "\n".join(lines)

    @tree.command(name="usage", description="Claude 토큰 사용량 및 비용 확인")
    async def usage(interaction: discord.Interaction):
        """누적된 토큰 사용량과 비용을 보여준다."""
        if not is_allowed_user(interaction):
            await interaction.response.send_message("권한이 없습니다.", ephemeral=True)
            return

        today_data = usage_tracker.get_today()
        total_data = usage_tracker.get_total()

        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")

        msg = "\n\n".join([
            "📊 **Claude 사용량**",
            _format_usage(f"오늘 ({today})", today_data),
            _format_usage("전체 누적", total_data),
        ])
        await interaction.response.send_message(msg, ephemeral=True)

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
            args=["-p", prompt, "--output-format", "json"],
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
            args=["-p", prompt, "--continue", "--output-format", "json"],
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
                "--output-format", "json",
                "--allowedTools", CODE_ALLOWED_TOOLS,
            ],
            prefix="**코드 수정 결과:**",
            cwd=TARGET_PROJECT,
            command_name="/code",
            detail=instruction[:100],
        )

    # ──────────────────────────────────────────
    # /commit-pr — 현재 변경사항을 커밋하고 PR 생성
    # ──────────────────────────────────────────
    @tree.command(name="commit-pr", description="현재 변경사항을 브랜치에 커밋하고 PR 생성")
    @app_commands.describe(branch="브랜치 이름", description="변경사항 설명 (커밋 메시지 및 PR 설명에 사용)")
    async def commit_pr(interaction: discord.Interaction, branch: str, description: str):
        """
        /code로 수정한 변경사항을 새 브랜치에 커밋하고 PR을 생성한다.
        코드 수정은 하지 않고, 현재 상태 그대로 커밋 → 푸시 → PR만 수행.
        """
        # 권한 확인
        if not is_allowed_user(interaction):
            await interaction.response.send_message("권한이 없습니다.", ephemeral=True)
            return

        # 브랜치 이름 검증
        error = validate_branch_name(branch)
        if error:
            await interaction.response.send_message(f"입력 오류:\n{error}", ephemeral=True)
            return

        full_prompt = (
            f"{SECURITY_PROMPT}"
            f"다음 작업을 순서대로 수행해줘:\n"
            f"1. git status로 현재 변경사항을 확인해\n"
            f"2. 변경사항이 없으면 '커밋할 변경사항이 없습니다'라고 알려주고 중단해\n"
            f"3. git checkout -b {branch}\n"
            f"4. 변경된 파일을 모두 git add 해 (.env 등 민감 파일은 제외)\n"
            f"5. 다음 설명을 기반으로 적절한 커밋 메시지를 작성하고 커밋해: {description}\n"
            f"6. git push -u origin {branch}\n"
            f"7. 다음 설명을 기반으로 PR을 생성해: {description}\n"
            f"   gh pr create --title '적절한 제목' --body '설명'\n"
            f"마지막에 PR URL을 출력해줘."
        )
        await handle_claude_command(
            interaction,
            args=[
                "-p", full_prompt,
                "--output-format", "json",
                "--allowedTools", PR_ALLOWED_TOOLS,
            ],
            prefix="**PR 생성 결과:**",
            cwd=TARGET_PROJECT,
            command_name="/commit-pr",
            detail=f"branch={branch} | {description[:80]}",
        )
