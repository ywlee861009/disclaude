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

## 보안 기능

| 기능 | 설명 |
|------|------|
| **접근 제어** | `ALLOWED_USER_ID`에 등록된 사용자만 명령어 실행 가능 |
| **Rate Limiting** | 사용자당 분당 요청 수 제한 (기본 10회, 환경변수로 조절) |
| **입력 검증** | `/gen-pr` 브랜치 이름을 화이트리스트 패턴으로 검증하여 인젝션 차단 |
| **민감 파일 차단** | `.env`, `*.pem`, `*.key` 등 민감 파일 접근을 시스템 프롬프트로 차단 |
| **응답 필터링** | Claude 응답에 토큰/비밀번호/API 키가 포함되면 `[REDACTED]`로 마스킹 |
| **감사 로그** | 모든 명령어 실행 기록을 `audit.log`에 저장 (사용자, 명령어, 내용) |

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
| `RATE_LIMIT_PER_MINUTE` | 분당 최대 요청 수 (기본값: `10`) | 선택 사항 |

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
