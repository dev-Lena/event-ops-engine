# 기여 안내

이 저장소는 팀 공용 개발 기준(작업 원칙 · 브랜치/커밋/PR · 코드 구조 · 테스트 · 비밀값/개인정보 · 용어)을 따른다. 공용 기준 문서는 별도 비공개 저장소에 있고 이 저장소에는 두지 않는다. 이 프로젝트에 적용된 내용은 아래와 [docs/design.md](docs/design.md) · [docs/glossary.md](docs/glossary.md)에 적혀 있다.

핵심만 요약하면:

- 작업 원칙: 무엇을 · 왜 · 검토한 대안을 먼저 보여주고, 완료라고 말하기 전에 실제로 실행 · 테스트한다. 확인하지 못한 것은 확인하지 못했다고 적는다.
- 브랜치 `type/short-desc`, 커밋 `type: subject`(영어), main 직접 push 금지, PR은 ~300줄 한 기능, 사람이 머지한다.
- 계산 로직은 같은 PR에 테스트를 올린다. 비밀값은 환경변수로만, 저장소에는 합성 데이터만.
- 용어는 한 개념 = 한 이름([docs/glossary.md](docs/glossary.md)).

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
영어는 번역이 아니라 현업 표현으로 따로 쓴다 . 공개 저장소를 한국어 · 영어 독자가 함께 보기 때문이다.

## PR 전 확인

`make check`가 모두 통과해야 한다. 실행하지 못한 확인은 PR에 "실행하지 못했다"고 적는다.
합성 데이터만 올린다. 실제 모임 데이터는 `data/private/`(gitignore) 밖으로 나가지 않는다.
