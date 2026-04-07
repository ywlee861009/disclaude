# Discord Claude Bot 셋업 가이드

## 프로젝트 구조
```
discord-claude-bot/
├── bot.py              # 메인 봇 코드
├── requirements.txt    # 파이썬 패키지 목록
├── .env                # 환경변수 (직접 생성)
├── .env.example        # 환경변수 템플릿
└── .gitignore
```

## Claude Code에게 줄 프롬프트

아래 프롬프트를 그대로 Claude Code에 붙여넣으면 프로젝트가 생성됩니다:

---

```
다음 파일들을 정확히 생성해줘. 내용을 절대 수정하지 말고 그대로 만들어줘.

### 1. bot.py

import os
import asyncio
import discord
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", "0"))
TARGET_PROJECT = os.getenv("TARGET_PROJECT_PATH")
CLAUDE_PATH = os.getenv("CLAUDE_PATH", "claude")

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
task_lock = asyncio.Lock()


def is_allowed(interaction: discord.Interaction) -> bool:
    return interaction.user.id == ALLOWED_USER_ID


async def run_claude(args: list[str], cwd: str = None) -> str:
    proc = await asyncio.create_subprocess_exec(
        CLAUDE_PATH, *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env={**os.environ, "FORCE_COLOR": "0"},
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
    except asyncio.TimeoutError:
        proc.kill()
        raise Exception("타임아웃: 5분 초과")
    if proc.returncode == 0:
        return stdout.decode().strip()
    else:
        raise Exception(stderr.decode().strip() or f"exit code {proc.returncode}")


async def send_long(interaction: discord.Interaction, text: str, prefix: str = ""):
    MAX = 1900
    content = f"{prefix}\n```\n{text}\n```" if prefix else text
    if len(content) <= 2000:
        await interaction.followup.send(content)
        return
    chunks = []
    while text:
        chunks.append(text[:MAX])
        text = text[MAX:]
    await interaction.followup.send(f"{prefix}\n```\n{chunks[0]}\n```")
    for chunk in chunks[1:]:
        await interaction.followup.send(f"```\n{chunk}\n```")


@tree.command(name="ping", description="봇 상태 확인")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong! 봇이 정상 작동 중입니다.")


@tree.command(name="ask", description="Claude Code에게 질문하기")
@app_commands.describe(prompt="질문 내용")
async def ask(interaction: discord.Interaction, prompt: str):
    if not is_allowed(interaction):
        await interaction.response.send_message("권한이 없습니다.", ephemeral=True)
        return
    await interaction.response.defer()
    async with task_lock:
        try:
            result = await run_claude(["-p", prompt, "--output-format", "text"])
            await send_long(interaction, result, "**Claude 응답:**")
        except Exception as e:
            await interaction.followup.send(f"오류 발생:\n```\n{str(e)[:1800]}\n```")


@tree.command(name="continue_chat", description="이전 대화 이어서 질문")
@app_commands.describe(prompt="이어서 할 질문")
async def continue_chat(interaction: discord.Interaction, prompt: str):
    if not is_allowed(interaction):
        await interaction.response.send_message("권한이 없습니다.", ephemeral=True)
        return
    await interaction.response.defer()
    async with task_lock:
        try:
            result = await run_claude(["-p", prompt, "--continue", "--output-format", "text"])
            await send_long(interaction, result, "**Claude 응답 (이어서):**")
        except Exception as e:
            await interaction.followup.send(f"오류 발생:\n```\n{str(e)[:1800]}\n```")


@tree.command(name="code", description="프로젝트 코드 수정 지시")
@app_commands.describe(instruction="수정 지시 내용")
async def code(interaction: discord.Interaction, instruction: str):
    if not is_allowed(interaction):
        await interaction.response.send_message("권한이 없습니다.", ephemeral=True)
        return
    await interaction.response.defer()
    async with task_lock:
        try:
            result = await run_claude(
                ["-p", instruction, "--output-format", "text",
                 "--allowedTools", "Edit,Write,Read,Glob,Grep,Bash"],
                cwd=TARGET_PROJECT,
            )
            await send_long(interaction, result, "**코드 수정 결과:**")
        except Exception as e:
            await interaction.followup.send(f"오류 발생:\n```\n{str(e)[:1800]}\n```")


@tree.command(name="gen-pr", description="브랜치 생성 → 코드 수정 → PR 자동 생성")
@app_commands.describe(branch="브랜치 이름", instruction="수정 지시 내용")
async def gen_pr(interaction: discord.Interaction, branch: str, instruction: str):
    if not is_allowed(interaction):
        await interaction.response.send_message("권한이 없습니다.", ephemeral=True)
        return
    await interaction.response.defer()
    async with task_lock:
        try:
            full_prompt = (
                f"다음 작업을 순서대로 수행해줘:\n"
                f"1. git checkout -b {branch}\n"
                f"2. {instruction}\n"
                f"3. 변경사항을 커밋해\n"
                f"4. git push -u origin {branch}\n"
                f"5. gh pr create --fill\n"
                f"마지막에 PR URL을 출력해줘."
            )
            result = await run_claude(
                ["-p", full_prompt, "--output-format", "text",
                 "--allowedTools", "Edit,Write,Read,Glob,Grep,Bash"],
                cwd=TARGET_PROJECT,
            )
            await send_long(interaction, result, "**PR 생성 결과:**")
        except Exception as e:
            await interaction.followup.send(f"오류 발생:\n```\n{str(e)[:1800]}\n```")


@client.event
async def on_ready():
    await tree.sync()
    print(f"봇 로그인 완료: {client.user}")


client.run(DISCORD_TOKEN)


### 2. requirements.txt

discord.py==2.7.1
python-dotenv==1.2.2


### 3. .env.example

DISCORD_TOKEN=your_bot_token_here
DISCORD_CLIENT_ID=your_client_id_here
ALLOWED_USER_ID=your_discord_user_id_here
TARGET_PROJECT_PATH=/path/to/your/project
CLAUDE_PATH=claude


### 4. .gitignore

venv/
__pycache__/
.env

```

---

## 셋업 순서

### 1. 파일 생성 후 가상환경 설정
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. .env 파일 생성
```bash
cp .env.example .env
```

그리고 `.env`를 열어서 값 채우기:

| 변수 | 설명 | 확인 방법 |
|------|------|-----------|
| `DISCORD_TOKEN` | 봇 토큰 | Discord 개발자 포털 → Bot → Reset Token |
| `DISCORD_CLIENT_ID` | 앱 ID | Discord 개발자 포털 → General Information |
| `ALLOWED_USER_ID` | 본인 Discord 숫자 ID | 개발자 모드 ON → 프로필 우클릭 → ID 복사 |
| `TARGET_PROJECT_PATH` | 제어할 프로젝트 경로 | 예: `/home/user/my-project` |
| `CLAUDE_PATH` | Claude CLI 경로 | `which claude` 로 확인 |

### 3. Discord 봇 초대
아래 URL에서 `YOUR_CLIENT_ID`를 실제 값으로 교체 후 브라우저에서 열기:
```
https://discord.com/oauth2/authorize?client_id=YOUR_CLIENT_ID&permissions=2147485696&scope=bot%20applications.commands
```

### 4. 봇 실행
```bash
source venv/bin/activate
python3 bot.py
```

슬립 방지 (macOS):
```bash
caffeinate -i python3 bot.py
```

## 사용 가능한 커맨드

| 커맨드 | 설명 |
|--------|------|
| `/ping` | 봇 상태 확인 |
| `/ask prompt:질문` | Claude Code에 일반 질문 |
| `/continue_chat prompt:질문` | 이전 대화 이어서 질문 |
| `/code instruction:지시` | 프로젝트 코드 수정 |
| `/gen-pr branch:이름 instruction:지시` | 자동 PR 생성 |

## 대화형 작업 흐름
```
/code instruction:로그인 화면 분석해줘
/continue_chat prompt:자동로그인 기능 추가해줘
/continue_chat prompt:변경사항 커밋하고 PR 만들어줘
```
