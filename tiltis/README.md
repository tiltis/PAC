# PAC 2026 — Claude Code · Codex 공동 작업

작업 시작 전에 상대의 코드와 인계 기록을 읽고, 쓸 수 있는 구현은 이어서 사용하고 문제는 근거와 테스트를 붙여 수정한다.

| 폴더 | 현재 구현 | 실행·인계 |
| --- | --- | --- |
| [claude-code/](claude-code/) | 기존 센서 서버와 로봇 검사 스테이션 | [README](claude-code/README.md), [HANDOFF](claude-code/HANDOFF.md) |
| [codex/](codex/) | 손목 추적 → XY 목표 → 모의/SDK 연결 어댑터 | [README](codex/README.md), [HANDOFF](codex/HANDOFF.md) |

공통 작업 방법은 [COLLABORATION.md](COLLABORATION.md), 에이전트 지침은 [AGENTS.md](AGENTS.md)에 있다.

기존 `tiltis/PAC2026_system/`은 `tiltis/claude-code/PAC2026_system/`으로 이동했다. 원래 커밋 `0e515a7`의 시스템 파일 내용은 보존했다. 폴더 배치는 이전 코드의 작성자를 소급해서 의미하지 않는다. 로컬 배포 위치 `C:\PAC2026_system`은 별도로 유지한다.

검사 시스템 설치·실행: [README](claude-code/PAC2026_system/README.md), 센서↔스테이션 계약: [CONTRACT](claude-code/PAC2026_system/CONTRACT.md), 현장 순서: [내일_로봇_순서](claude-code/PAC2026_system/내일_로봇_순서.md).

가상환경, 촬영 영상, 실행 로그, DB, 토큰 및 개인 보정 파일은 올리지 않는다. 실제 로봇 모델과 현장 범위는 아직 확인되지 않았다.
