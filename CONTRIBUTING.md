# 기여 안내

이 저장소는 `~/Projects/dev-standards`의 공용 기준을 그대로 따른다. 사본은 [docs/standards/](docs/standards/)에 있다.

| 무엇 | 문서 |
|---|---|
| 작업 원칙 (이유와 함께 제안 · 실제 실행 확인 · 품질 · 토큰) | [working-principles.md](docs/standards/working-principles.md) |
| 브랜치 · 커밋 · PR | [git-workflow.md](docs/standards/git-workflow.md) |
| 코드 구조 · 클린 코드 | [code-standards.md](docs/standards/code-standards.md) |
| 테스트 | [testing-standards.md](docs/standards/testing-standards.md) |
| 비밀값 · 개인정보 | [security-standards.md](docs/standards/security-standards.md) |
| 작업 시작 전 환경 · 계정 | [environment-setup.md](docs/standards/environment-setup.md) |
| 용어 기준 | [terminology.md](docs/standards/terminology.md) → 이 프로젝트 용어는 [docs/glossary.md](docs/glossary.md) |

## 이 프로젝트에서 다르게 하는 것

| 항목 | 기준 | 여기서는 | 이유 |
|---|---|---|---|
| 테스트 파일 위치 | 대상 파일 바로 옆 `*.test.*` | `tests/` 폴더, `test_<module>.py` | Python 패키징에서 테스트를 배포 패키지 밖에 두는 관례. pytest 기본 설정과 맞춤 |
| 테스트 도구 | Vitest · Playwright | pytest (E2E 없음: 화면이 없다) | Python 프로젝트 |
| 린트 · 타입 | eslint · tsc | black · isort · flake8 · mypy(strict) | Python 프로젝트 |
| 계층 이름 | screens / patterns / ui / services / lib | `features`(capacity · promotion · cli) / `services`(engine) / `lib`(model · facts · bands · clock · policy) — 폴더는 나누지 않고 모듈 docstring에 계층을 적는다 | 모듈 수가 적다. 10개를 넘기면 폴더로 나눈다 |

## 시작하기

```bash
python3.11 -m venv .venv && source .venv/bin/activate
make install
make check        # lint + typecheck + test
```

Intel Mac은 엔진을 한 번 빌드해야 한다 ([README](README.md) "설치").

## 기록 언어

이슈 제목 · 본문과 PR 본문은 한국어 + 영어(한 본문, 한국어 → `---` → 영어), 판단 근거 · 리뷰 기록 코멘트는 언어별로 따로 올린다.
영어는 번역이 아니라 현업 표현으로 따로 쓴다 ([git-workflow.md 5절](docs/standards/git-workflow.md#5-언어)). 공개 저장소를 한국어 · 영어 독자가 함께 보기 때문이다.

## PR 전 확인

`make check`가 모두 통과해야 한다. 실행하지 못한 확인은 PR에 "실행하지 못했다"고 적는다.
합성 데이터만 올린다. 실제 모임 데이터는 `data/private/`(gitignore) 밖으로 나가지 않는다.
