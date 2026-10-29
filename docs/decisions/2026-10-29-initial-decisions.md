# 2026-10-29 초기 결정

핸드오프 문서 §9의 항목과 세션에서 추가된 항목을 사용자가 **추천안대로** 승인했다.

| # | 항목 | 결정 | 이유 |
|---|---|---|---|
| 1 | 저장소 | `~/Projects/GitHub/event-ops-engine`, 원격 `dev-Lena/event-ops-engine` | 핸드오프 추천 위치와 같음 |
| 2 | 라이선스 | Apache-2.0 | PyreWire(Apache-2.0/GPL-3.0)와 맞고, LGPL 엔진은 동적 연결이라 저장소 라이선스에 영향 없음 |
| 3 | LLM 실행 | Claude Code CLI + 테스트용 가짜 해석기 | 추가 비용 0, 테스트 재현성. ②·③은 LLM을 쓰지 않는다 |
| 4 | 공개 시점 | 비공개 유지 → 합성 데이터·문서 점검 후 공개 전환(사용자가 직접) | 고객 정보 혼입 점검이 먼저 |
| 5 | 1차 속성 | 성별(비율 포함) + 나이 구간 | 11/1 일정 |
| 6 | 홍보 기준값 | `lead_days 7`, `trend_min_per_week 3`을 **가정값**으로 정책 파일에 둔다 | 실제 값은 운영사 정책 |
| 7 | 엔진 소스 보관 | `vendor/`는 gitignore, `scripts/build-wirelog.sh`로 재현. CI(ubuntu)는 wheel 엔진 | submodule은 무겁고 Intel Mac만 필요한 절차 |
| 8 | git 로컬 작성자 | `git config --local`로 user.name · user.email · credential username 고정 | environment-setup §3 |
| 9 | wirelog 0.70 제약 우회 | design.md 9절에 기록 | 핸드오프 §6-1 "조정한 내용은 알린다" |
| 10 | 패키지 도구 | `pyproject.toml` + venv + pip | 의존성이 적어 lock 도구 불필요 |
