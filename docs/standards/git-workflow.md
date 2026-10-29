# Git 기준 — 브랜치 · 커밋 · PR

어느 프로젝트든 같은 방식으로 브랜치를 나누고, 커밋을 남기고, PR로 리뷰 · 머지한다. 사람이든 Claude든 같은 규칙을 따른다.
프로젝트 이름 · 기술에 기대지 않게 쓴다. 예시의 브랜치 · 명령은 예시일 뿐이고, 프로젝트별 명령(테스트 · 스크린샷 스크립트 등)은 프로젝트 문서에 적는다.

| # | 주제 | 핵심 |
|---|---|---|
| 1 | [브랜치](#1-브랜치) | `type/짧은-설명`, `main` 직접 커밋 금지, PR 수동 머지 |
| 2 | [커밋](#2-커밋) | 영어 `type: subject`, 한 task = 한 commit, Claude 서명 줄 없음 |
| 3 | [PR](#3-pr) | `main` 대상 · 쌓지 않기, 커밋 전 PR 열림 확인, 배경과 판단 근거 코멘트 |
| 4 | [스크린샷 · 이미지](#4-스크린샷--이미지) | 화면 · 이미지 변경 PR은 필수, `pr-assets` 브랜치 |
| 5 | [언어](#5-언어) | 이슈 · PR · 커밋 · 코드별 언어 |
| A | [부록 A. PR 템플릿](#부록-a-pr-템플릿) | `.github/pull_request_template.md` |
| B | [부록 B. 커밋 템플릿](#부록-b-커밋-템플릿) | `.gitmessage.txt` |

---

## 1. 브랜치

```
main                         배포 기준
feat/signup-email-input      기능
fix/date-timezone-boundary   버그
docs/dev-spec                문서
refactor/profile-service     리팩터링
chore/setup-error-tracking   설정
```

- 하나의 기능 단위로 **작게** 나눠 브랜치를 만든다. 이름은 `type/짧은-설명` (영어, kebab-case). `type`은 커밋 type과 같은 목록을 쓴다 ([부록 B](#부록-b-커밋-템플릿)).
- **`main`에 직접 커밋하지 않는다.** 모든 변경은 브랜치 → PR을 거친다. main은 언제나 리뷰를 거친 배포 가능한 상태로 둔다.
- PR은 **수동 머지**한다. 자동 머지(auto-merge)를 켜지 않는다 — 사람이 마지막으로 확인하고 누른다.
- PR은 CI(lint · 타입 검사 · 테스트 · 빌드)를 통과해야 머지한다.

## 2. 커밋

- **영어**, **한 task = 한 commit**. 관계없는 변경을 한 커밋에 섞지 않는다 → 되돌리기 · 리뷰 · 기록 찾기가 쉽다.
- 형식은 `type: subject`. 이슈 번호는 **footer에만** 적는다.
- 템플릿: [부록 B](#부록-b-커밋-템플릿)를 저장소 루트 `.gitmessage.txt`로 두고 `git config commit.template .gitmessage.txt`.

```
feat: add email format check to signup form

Refs: #<이슈 번호>
```

| 부분 | 규칙 |
|---|---|
| subject | 50자 이내 · 영어 · 명령형 · 소문자로 시작 · 마침표 없음 |
| body (선택) | 무엇을 · 왜. 한 줄 72자 이내 |
| footer | `Refs: #<번호>` (관련 이슈), `Closes: #<번호>` (이 커밋으로 닫히는 이슈) |

| type | 쓰는 때 |
|---|---|
| `feat` | 새로운 기능 |
| `fix` | 버그 수정 |
| `docs` | 문서 |
| `style` | 포맷팅 (동작 변경 없음) |
| `refactor` | 리팩터링 (기능 변경 없음) |
| `test` | 테스트 추가 · 수정 |
| `chore` | 빌드 · 설정 · 의존성 |
| `perf` | 성능 개선 |

### Claude 서명 줄을 넣지 않는다

커밋 메시지에 `Co-Authored-By: Claude …` 같은 서명 줄을 넣지 않는다 (PR 본문도 같음 — [3번](#3-pr)).
기록은 작업 내용만 남기고, 작성자는 커밋한 사람 한 명으로 둔다.

- Claude Code에서는 설정으로 끈다. 프로젝트 `.claude/settings.json`(팀 공통)이나 `~/.claude/settings.json`(내 모든 프로젝트)에:

```json
{
  "attribution": { "commit": "", "pr": "" }
}
```

- 도구가 자동으로 붙였으면 커밋 · PR을 올리기 전에 지운다.

## 3. PR

- 모든 PR은 **`main`을 대상**으로 한다. 다른 PR 브랜치 위에 **쌓지 않는다**(stacked PR 금지) — 앞 PR이 바뀌거나 먼저 머지되면 뒤 PR의 대상 · 충돌이 꼬인다. 앞 작업이 필요하면 그 PR이 머지된 뒤 main에서 새 브랜치를 딴다.
- 본문은 [PR 템플릿](#부록-a-pr-템플릿)을 채운다 (한국어 + 영어). 본문에는 **무엇이 바뀌었는지**를 적는다.
- PR을 만든 직후, 본문과 **별도의 코멘트**로 "배경과 판단 근거"를 남긴다 (한국어). 리뷰어가 코드를 보기 전에 **왜 이 작업을 이렇게 했는지** 이해하기 위해서다.
- PR 본문 · 코멘트에도 **Claude 서명 줄**(`🤖 Generated with Claude Code` 등)을 넣지 않는다 ([2번](#claude-서명-줄을-넣지-않는다)).

### 커밋을 더하기 전에 PR이 아직 열려 있는지 확인한다

기존 브랜치에 커밋을 더하기 전에 그 브랜치의 PR 상태를 확인한다.
이미 머지 · 종료된 PR의 브랜치에 커밋을 올리면 **어느 PR에도 들어가지 않고 묻힌다** (리뷰도, main 반영도 안 된다).

```bash
gh pr view --json state,url -q '.state + " " + .url'   # 현재 브랜치의 PR 상태
```

| 결과 | 할 일 |
|---|---|
| `OPEN` | 그대로 커밋 · 푸시 |
| `MERGED` · `CLOSED` | 최신 main에서 새 브랜치를 따고 새 PR로 올린다 |
| PR 없음 (`no pull requests found`) | 올리려던 작업이 맞는지 확인하고 PR을 만든다 |

### 배경과 판단 근거 코멘트

아래 7항목을 빠짐없이 적는다. 해당 없는 항목은 "해당 없음"과 이유를 쓴다.

| 항목 | 적을 내용 |
|---|---|
| 왜 하는가 | 이 작업이 필요한 이유, 해결하려는 문제 |
| 목적 | 머지 후 무엇이 가능해지는지, 어떤 목표에 기여하는지 |
| 우선순위 | P0/P1/P2와 그 이유, 다른 작업과의 선후 관계 |
| 판단 기준 | 선택할 때 무엇을 기준으로 삼았는지 (비용 · 단순함 · 확장성 · 기획 의도 등) |
| 왜 그렇게 판단했나 | 기준을 적용한 결과, 검토한 대안과 고르지 않은 이유 |
| 왜 이렇게 구현했나 | 주요 설계 · 구현 결정과 이유 (표로 정리해도 좋다) |
| 고려할 점 · 주의할 점 | 알려진 한계, 후속 작업, 머지 · 배포 시 주의사항, 리뷰어가 특히 볼 곳 |

```markdown
## 이 PR의 배경과 판단 근거

**왜 하는가**
**목적**
**우선순위**
**판단 기준**
**왜 그렇게 판단했나** (검토한 대안 포함)
**왜 이렇게 구현했나**
**고려할 점 · 주의할 점**
```

- Dependabot PR처럼 사람이 만들지 않은 PR은 코멘트를 생략해도 된다. 대신 닫거나 보류할 때 이유를 코멘트로 남긴다.

## 4. 스크린샷 · 이미지

**화면(UI · UX)을 만들거나 바꾼 PR, 이미지를 만들거나 바꾼 PR은 본문에 스크린샷 · 이미지를 반드시 넣는다.** 리뷰어가 코드를 실행하지 않고도 결과를 디자인 시안과 비교할 수 있어야 한다.

| 무엇이 바뀌었나 | 넣을 이미지 |
|---|---|
| 화면 · 레이아웃 | 모바일(390px) + PC(1440px) — 기본값, 프로젝트가 다르게 정했으면 그 값 |
| 문구 | 지원하는 언어별 (예: 한국어 + 영어) |
| 컴포넌트 | 상태별(기본 · 선택 · 비활성 · 오류 · 눌림 등) 한 장에 모은 화면 |
| 동작 · 흐름 (애니메이션, 화면 전환) | 단계별 스크린샷 또는 짧은 영상 · GIF |
| 이미지 · 에셋 · 공유 카드 | 결과 이미지 원본 |
| 디자인과 다르게 만든 부분 | 시안과 나란히 놓은 비교 이미지 + 이유 |

- 가능하면 **디자인 시안 스크린샷을 같이** 넣어 비교할 수 있게 한다.
- 화면이 없는 PR(문서 · 설정 · 순수 로직)은 "해당 없음"이라고 적는다.

### 이미지는 `pr-assets` 브랜치에 올린다

이미지는 코드와 섞지 않고 저장소의 **`pr-assets` 브랜치**(코드 기록과 이어지지 않는 별도 브랜치)에 올려 PR 본문에서 참조한다.

- main 기록에 이미지가 쌓이지 않는다 → 저장소 크기 · 클론 시간이 늘지 않는다.
- 저장소 안에 있으므로 **비공개 저장소 권한이 있는 사람에게만** 보인다 (외부 이미지 호스팅에 올리지 않는다).

절차 (프로젝트에서 스크립트로 만들어 둔다):

1. 앱을 로컬에서 띄우고, 바뀐 화면을 위 표의 조합(뷰포트 × 언어 × 상태)으로 찍는다.
2. `pr-assets` 브랜치의 `pr/<PR 번호>/` 폴더에 이미지를 올린다. 작업 중인 폴더를 건드리지 않도록 임시 폴더에 그 브랜치만 얕게 받아(`git clone --depth 1 --branch pr-assets`) 올린다. 브랜치가 없으면 `--orphan`으로 새로 만든다.
3. 올린 파일 주소(`https://github.com/<owner>/<repo>/blob/pr-assets/pr/<번호>/<파일>?raw=true`)로 본문 마크다운을 만들어 붙인다.

> 예 (LuckPlay): `node scripts/screenshots.mjs <경로...>`가 모바일 · PC × 한국어 · 영어로 찍고, `sh scripts/pr-assets.sh <PR 번호> screenshots/*.png`가 `pr-assets`에 올린 뒤 본문용 마크다운을 출력한다.

## 5. 언어

기본값이다. 프로젝트 사용자 · 팀에 맞춰 바꾸면 프로젝트 문서에 적는다.

| 대상 | 언어 |
|---|---|
| 이슈 | 한국어 |
| PR 본문 | 한국어 + 영어 |
| PR 배경 · 판단 근거 코멘트 | 한국어 |
| 커밋 메시지 | 영어 |
| 브랜치명 | 영어 |
| 코드 주석 | 한국어 허용 |
| 코드 식별자 (변수 · 함수 · DB 컬럼) | 영어 |

---

## 부록 A. PR 템플릿

저장소의 `.github/pull_request_template.md`로 복사한다. "확인 방법"의 명령은 프로젝트 것으로 바꾼다 (아래는 npm 프로젝트 예).

````markdown
## 요약 / Summary

<!-- 무엇을 왜 바꿨는지 / What changed and why -->

-

## 변경 사항 / Changes

-

## 스크린샷 / Screenshots

<!--
화면(UI · UX)이나 이미지를 만들거나 바꿨다면 반드시 넣는다 — 모바일 + PC, 언어별, 상태별. 가능하면 디자인 시안도 함께.
이미지는 pr-assets 브랜치에 올려 참조한다 (git-workflow.md > 4. 스크린샷 · 이미지).
Required for any UI or image change. 화면이 없으면 "해당 없음 / N/A".
-->

## 확인 방법 / How to verify

- [ ] `npm test`
- [ ] `npm run test:e2e` (화면 · 흐름 변경 시 / for UI or flow changes)
- [ ] `npm run typecheck`
- [ ] `npm run lint`
- [ ] `npm run build`
- [ ] 화면 · 이미지 변경 시 위 스크린샷 섹션 채움 / Screenshots section filled for UI or image changes

## 관련 이슈 / Related issues

Closes #

<!--
PR을 만든 뒤 본문과 별도로 "배경과 판단 근거" 코멘트를 남겨주세요 (git-workflow.md > 3. PR).
왜 하는가 · 목적 · 우선순위 · 판단 기준 · 왜 그렇게 판단했나 · 왜 이렇게 구현했나 · 고려할 점/주의할 점
After opening the PR, post a separate rationale comment (see git-workflow.md > 3. PR).
Claude 서명 줄을 넣지 않습니다 / No Claude attribution lines.
-->
````

## 부록 B. 커밋 템플릿

저장소 루트의 `.gitmessage.txt`로 복사하고 `git config commit.template .gitmessage.txt`로 연결한다. `#`로 시작하는 줄은 커밋에 들어가지 않는다.

```
# <type>: <subject>            ← 50자 이내, 영어, 명령형, 소문자 시작, 마침표 없음
#
# ─────────────────────────────────────────────
# <body>                       ← 무엇을/왜 (선택). 한 줄 72자 이내
#
# ─────────────────────────────────────────────
# Refs: #<issue-number>        ← 관련 이슈
# Closes: #<issue-number>      ← 이 커밋으로 닫히는 이슈
#
# ═════════════════════════════════════════════
# type
#   feat      새로운 기능
#   fix       버그 수정
#   docs      문서
#   style     포맷팅 (동작 변경 없음)
#   refactor  리팩터링 (기능 변경 없음)
#   test      테스트 추가/수정
#   chore     빌드·설정·의존성
#   perf      성능 개선
#
# 예시
#   feat: add email format check to signup form
#   feat: show character count on profile name input
#   fix: use user time zone for day boundary
#   docs: add api error code table
#   refactor: extract profile update service
#   chore: set up error tracking for server
#
# 규칙
#   - 하나의 task = 하나의 커밋
#   - subject는 소문자로 시작, 영어
#   - 이슈 번호는 footer에만
#   - Co-Authored-By: Claude 같은 서명 줄을 넣지 않는다
# ═════════════════════════════════════════════
```

## 기록

| 날짜 | 내용 |
|---|---|
| 2026-09-26 | 처음 만듦 (LuckPlay CONTRIBUTING · PR 템플릿 · 커밋 템플릿에서 정리). main 직접 커밋 금지 · 수동 머지, PR 쌓지 않기, 커밋 전 PR 열림 확인, Claude 서명 줄 금지 추가 |
