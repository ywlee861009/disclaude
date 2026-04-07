# disclaude

디스코드에서 슬래시 명령어로 Claude Code를 원격 제어하는 봇.

## 사용 가능한 명령어

| 명령어 | 설명 | 예시 |
|--------|------|------|
| `/ping` | 봇 상태 확인 | `/ping` |
| `/ask` | Claude에게 일반 질문 | `/ask prompt:Python에서 GIL이 뭐야?` |
| `/continue_chat` | 이전 대화 이어서 질문 | `/continue_chat prompt:좀 더 자세히 설명해줘` |
| `/code` | 프로젝트 코드 수정 지시 | `/code instruction:로그인 API에 rate limit 추가해줘` |
| `/gen-pr` | 브랜치 생성 + 코드 수정 + PR 자동 생성 | `/gen-pr branch:feat/rate-limit instruction:로그인 API에 rate limit 추가` |

## 사용 예시

### 단순 질문
```
/ask prompt:FastAPI에서 미들웨어 추가하는 방법 알려줘
```

### 코드 수정
```
/code instruction:README.md에 설치 방법 섹션 추가해줘
```

### 대화형 작업 흐름
```
/code instruction:로그인 화면 분석해줘
/continue_chat prompt:자동로그인 기능 추가해줘
/continue_chat prompt:변경사항 커밋하고 PR 만들어줘
```

### PR 자동 생성
```
/gen-pr branch:feat/auto-login instruction:자동로그인 기능을 구현해줘
```

## 빠른 시작

### 1. 사전 요구사항
- Python 3.12+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) 설치 및 인증 완료
- 디스코드 봇 생성 ([Developer Portal](https://discord.com/developers/applications))

### 2. 설치
```bash
git clone https://github.com/Moon-Metrex/disclaude.git
cd disclaude

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. 환경변수 설정
```bash
cp .env.example .env
```

`.env` 파일을 열어 값을 채워넣기:

| 변수 | 설명 | 확인 방법 |
|------|------|-----------|
| `DISCORD_TOKEN` | 봇 토큰 | Developer Portal → Bot → Reset Token |
| `ALLOWED_USER_ID` | 본인 디스코드 ID | 개발자 모드 ON → 프로필 우클릭 → ID 복사 |
| `TARGET_PROJECT_PATH` | 코드 수정 대상 프로젝트 경로 | 예: `/Users/me/my-project` |
| `CLAUDE_PATH` | Claude CLI 경로 (기본값: `claude`) | `which claude`로 확인 |

### 4. 디스코드 봇 초대

아래 URL에서 `YOUR_CLIENT_ID`를 실제 값으로 교체 후 브라우저에서 열기:
```
https://discord.com/oauth2/authorize?client_id=YOUR_CLIENT_ID&permissions=2147485696&scope=bot%20applications.commands
```

### 5. 실행
```bash
source venv/bin/activate
python3 bot.py
```

macOS에서 슬립 방지:
```bash
caffeinate -i python3 bot.py
```

## 참고사항

- `ALLOWED_USER_ID`에 설정된 사용자만 명령어를 사용할 수 있습니다.
- Claude 응답 시간은 최대 5분이며, 초과 시 타임아웃됩니다.
- 동시에 여러 명령어를 실행할 수 없습니다 (순차 처리).
- 자세한 셋업 가이드는 [SETUP.md](SETUP.md)를 참고하세요.
