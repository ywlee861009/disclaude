"""
disclaude — Discord + Claude Code 연동 봇 패키지
=================================================
디스코드 슬래시 명령어를 통해 Claude Code CLI를 원격으로 제어한다.

모듈 구성:
  config         : 환경변수, 상수 정의
  security       : 접근 제어, Rate Limiting, 검증, 마스킹, 감사 로그
  claude_runner  : Claude Code CLI 실행 및 응답 분할 전송
  commands       : 슬래시 명령어 정의
"""
