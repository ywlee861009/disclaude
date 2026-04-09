"""
claude_runner — Claude Code CLI 실행기
=======================================
Claude Code CLI를 서브프로세스로 실행하고,
디스코드 메시지 길이 제한에 맞춰 응답을 분할 전송한다.
"""

import os
import logging
import asyncio

import discord

from .config import CLAUDE_PATH, CLAUDE_TIMEOUT, COMMAND_TIMEOUTS, DISCORD_MAX_LENGTH, PROGRESS_NOTIFICATIONS
from .security import sanitize_output

# Claude 서브프로세스에 전달할 환경변수 화이트리스트
# 민감 정보(DISCORD_TOKEN 등)가 Claude에 노출되지 않도록 필요한 것만 전달
_SAFE_ENV_KEYS = {"PATH", "HOME", "USER", "LANG", "LC_ALL", "SHELL", "TERM", "TMPDIR"}

logger = logging.getLogger("disclaude")


async def _send_progress(interaction: discord.Interaction, timeout: int) -> None:
    """
    Claude 실행 중 일정 간격으로 진행 상태 알림을 전송한다.
    타임아웃 이하인 알림만 전송한다. 외부에서 cancel()로 중단.
    """
    elapsed = 0
    for seconds, message in PROGRESS_NOTIFICATIONS:
        if seconds >= timeout:
            break
        wait = seconds - elapsed
        if wait > 0:
            await asyncio.sleep(wait)
        elapsed = seconds
        try:
            await interaction.followup.send(message, silent=True)
        except discord.HTTPException:
            logger.warning("진행 알림 전송 실패 (%d초)", seconds)


async def run_claude(
    args: list[str],
    cwd: str | None = None,
    command_name: str | None = None,
) -> str:
    """
    Claude Code CLI를 서브프로세스로 실행하고 결과를 반환한다.

    Args:
        args:         Claude CLI에 전달할 인자 리스트 (예: ["-p", "질문 내용"])
        cwd:          작업 디렉토리. None이면 현재 디렉토리 사용.
        command_name: 명령어 이름 (타임아웃 결정용, 예: "/ask", "/code")

    Returns:
        Claude CLI의 stdout 출력 (민감 정보 마스킹 적용됨)

    Raises:
        Exception: 타임아웃 초과 또는 비정상 종료 시
    """
    timeout = COMMAND_TIMEOUTS.get(command_name, CLAUDE_TIMEOUT)
    logger.info("Claude 실행: args=%s, cwd=%s, timeout=%ds", args, cwd, timeout)

    # 안전한 환경변수만 선별하여 전달 (DISCORD_TOKEN 등 민감 정보 차단)
    safe_env = {k: v for k, v in os.environ.items() if k in _SAFE_ENV_KEYS}
    safe_env["FORCE_COLOR"] = "0"  # ANSI 색상 코드 제거 (디스코드 출력용)

    proc = await asyncio.create_subprocess_exec(
        CLAUDE_PATH, *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=safe_env,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()  # 좀비 프로세스 방지
        logger.error("Claude 프로세스 타임아웃 (%d초 초과)", timeout)
        raise Exception(f"타임아웃: {timeout}초 초과")

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
    followup 전송 실패 시 채널 직접 전송으로 폴백한다.

    Args:
        interaction: 디스코드 인터랙션 객체
        text:        전송할 텍스트
        prefix:      첫 번째 메시지 앞에 붙일 접두사 (예: "**Claude 응답:**")
    """
    # 텍스트를 청크로 분할
    chunks: list[str] = []
    if not text:
        chunks.append("(빈 응답)")
    else:
        remaining = text
        while remaining:
            chunks.append(remaining[:DISCORD_MAX_LENGTH])
            remaining = remaining[DISCORD_MAX_LENGTH:]

    messages: list[str] = []
    messages.append(f"{prefix}\n```\n{chunks[0]}\n```" if prefix else f"```\n{chunks[0]}\n```")
    for chunk in chunks[1:]:
        messages.append(f"```\n{chunk}\n```")

    for msg in messages:
        try:
            await interaction.followup.send(msg)
        except discord.HTTPException:
            # interaction 만료 시 채널 직접 전송으로 폴백
            logger.warning("followup 전송 실패, 채널 직접 전송으로 전환")
            try:
                await interaction.channel.send(msg)
            except discord.HTTPException:
                logger.error("채널 메시지 전송도 실패")
                return
