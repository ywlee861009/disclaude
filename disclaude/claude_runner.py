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

from .config import CLAUDE_PATH, CLAUDE_TIMEOUT, DISCORD_MAX_LENGTH
from .security import sanitize_output

logger = logging.getLogger("disclaude")


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
