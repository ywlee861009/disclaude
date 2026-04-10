"""
disclaude — Discord + Claude Code 연동 봇
==========================================
엔트리포인트. 디스코드 클라이언트를 초기화하고 봇을 실행한다.

실행 방법:
  python3 bot.py

패키지 구조:
  disclaude/
  ├── __init__.py      : 패키지 초기화
  ├── config.py        : 환경변수, 상수 정의
  ├── security.py      : 접근 제어, Rate Limiting, 검증, 마스킹, 감사 로그
  ├── claude_runner.py : Claude Code CLI 실행 및 응답 분할 전송
  └── commands.py      : 슬래시 명령어 정의
"""

import logging
from logging.handlers import TimedRotatingFileHandler

import discord
from discord import app_commands

from disclaude.config import DISCORD_TOKEN, RATE_LIMIT_PER_MINUTE
from disclaude.security import RateLimiter
from disclaude.commands import register_commands

# ──────────────────────────────────────────────
# 로깅 설정
# ──────────────────────────────────────────────
_file_handler = TimedRotatingFileHandler(
    "bot.log", when="midnight", backupCount=30, encoding="utf-8",
)
_file_handler.namer = lambda name: name.replace("bot.log.", "bot_").replace("-", "") + ".log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        _file_handler,
    ],
)
logger = logging.getLogger("disclaude")

# ──────────────────────────────────────────────
# 디스코드 클라이언트 초기화
# ──────────────────────────────────────────────
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# Rate Limiter 인스턴스 생성
rate_limiter = RateLimiter(RATE_LIMIT_PER_MINUTE)

# 슬래시 명령어 등록
register_commands(tree, rate_limiter)

# 슬래시 명령어 동기화 여부 (최초 1회만 sync)
_commands_synced = False


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


@client.event
async def on_connect():
    """Discord Gateway에 연결되었을 때."""
    logger.info("Gateway 연결됨")


@client.event
async def on_disconnect():
    """Discord Gateway 연결이 끊어졌을 때."""
    logger.warning("Gateway 연결 끊김 — 자동 재연결 시도 중...")


@client.event
async def on_resumed():
    """Gateway 세션이 성공적으로 재개되었을 때."""
    logger.info("Gateway 세션 재개 완료")


# ──────────────────────────────────────────────
# 엔트리포인트
# ──────────────────────────────────────────────
if __name__ == "__main__":
    logger.info("disclaude 봇을 시작합니다...")
    client.run(DISCORD_TOKEN, log_handler=None)
