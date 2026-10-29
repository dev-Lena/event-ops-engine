# 설계 — 모임 운영 판단 엔진 (event-ops-engine)

회차별 신청 데이터를 **속성별 목표**와 견주어 현황을 내고, 홍보가 필요한지 판단하는 규칙 엔진이다.
규칙은 wirelog(Datalog)로 쓰고, Python은 입력을 사실(fact)로 바꾸고 결과에 근거를 붙이는 일만 한다.
용어는 [glossary.md](glossary.md)를 따른다. 결정 기록은 [decisions/](decisions/)에 있다.

## 1. 범위

| 모듈 | 하는 일 | LLM | 이번 PR |
|---|---|---|---|
| ② 현황 (capacity) | 회차 · 속성 값마다 `filled` · `gap` · `remaining` · 입금 대기 · 정원 대비 남은 자리 | 없음 | 구현 |
| ③ 홍보 판단 (promotion) | 부족분 · 남은 날 · 최근 추세 · 비율 불균형으로 홍보 **권고** 또는 **보류** | 없음 | 구현 |
| ① 운영 문의 판정 (triage) | 문의 글을 유형으로 해석(LLM) → 규칙으로 판정 → accept / ask / abstain / reject | 있음 | 다음 PR |

엔진은 **권고만** 한다. 홍보 실행 · 개별 신청 거절은 사람이 한다. 개별 신청자를 자동으로 거절하는 규칙은 두지 않는다.

## 2. 흐름

```
YAML 시나리오 ─► Python 모델(검증) ─► 사실(fact) ─► wirelog 규칙 ─► 파생 관계 ─► Decision(+근거) ─► CLI 출력
 policy/*.yaml    model.py            facts.py       rules/*.dl      engine.py     capacity.py / promotion.py   cli.py
                                      bands.py                                     
                                      clock.py
```

계층 ([standards/code-standards.md](standards/code-standards.md) 1번):

| 계층 | 모듈 | 규칙 |
|---|---|---|
| lib (순수) | `model.py` `bands.py` `clock.py` `facts.py` `policy.py` | 외부 라이브러리 · 시각을 모른다. 현재 시각은 인자로 받는다 |
| services | `engine.py` | PyreWire를 감싼다. wirelog 제약(9절)을 여기서 모두 흡수한다 |
| features | `capacity.py` `promotion.py` `cli.py` | 사실 적재 → 스냅샷 → `Decision` 조립 |

## 3. 데이터 모델 (Python, `model.py`)

```
Scenario
  policy: EventPolicy            # 속성 정의 · 기본 목표 · 홍보 기준
  now: datetime                  # 판단 기준 시각 (테스트 재현을 위해 입력으로 받는다)
  sessions: [Session]            # id, date, capacity, targets 덮어쓰기(선택)
  registrations: [Registration]  # id, session_id, members | party_size, status_events

Registration
  members: [Member] | None       # 참가자 목록. None이면 구성 미상(옛 신청)
  party_size: int                # members가 있으면 len과 같아야 한다
  status_events: [StatusEvent]   # (ts, status) — status는 glossary "상태 값" 다섯 개만
Member
  gender: female | male | unknown
  birth_year: int | None
```

개인 식별 정보 칸은 **모델에 없다**. 이름 · 연락처 · 계좌 · 자유 서술은 들어올 자리가 없으므로 실수로도 저장소 · 출력에 섞이지 않는다.

## 4. 인원 환산

정원과 목표는 **사람 수**다. 신청 1건을 참가자 n명으로 펼친다 (`facts.py`).

| 신청 | 참가자 | 성별 속성 |
|---|---|---|
| 1인 | 1 | 신청자 성별 |
| 2인 같은 성별 | 2 | 둘 다 같은 값 |
| 2인 혼성 | 2 | 1 + 1 |
| n명 단체 | n | 구성원마다 |
| 구성 미상 (옛 신청, `members: None`) | `party_size` | 모두 `unknown` → 목표 집계에서 빠지고 `needs_review`로 올라간다 |

참가자 id는 `<registration id>#<순번>`. 나이 구간은 `bands.py`가 `birth_year`와 회차 연도로 계산한다 (경계 규칙은 glossary).

## 5. 사실 스키마 (`rules/ontology.dl`)

| 관계 | 뜻 | 출처 |
|---|---|---|
| `session_capacity(session, capacity)` | 회차 정원 | 시나리오 |
| `days_left(session, days)` | 기준 시각에서 회차까지 남은 날 (음수면 지난 회차) | `clock.py` |
| `now(ts)` | 기준 시각 (epoch 초) | `clock.py` |
| `registration(reg, session)` | 신청이 속한 회차 | 시나리오 |
| `attendee(reg, attendee)` | 신청을 펼친 참가자 | `facts.py` |
| `attendee_attr(attendee, dim, value)` | 참가자 속성 | `facts.py` + `bands.py` |
| `status_event(reg, ts, status)` | 상태 이력 | 시나리오 |
| `unknown_party(reg, party_size)` | 구성 미상 신청 | `facts.py` |
| `target(session, dim, value, lo, hi)` | 속성 값 목표 | `policy.py` |
| `ratio_target(session, dim, value_a, value_b, max_diff)` | 비율 목표 | `policy.py` |
| `policy(session, key, n)` | 홍보 기준값 | `policy.py` |

## 6. 현황 규칙 (②, `rules/capacity.dl`)

```
latest_ts(R, max(T))        :- status_event(R, T, _).
current_status(R, St)       :- latest_ts(R, T), status_event(R, T, St).
confirmed(R)                :- current_status(R, "confirmed").
seat(S, A)                  :- registration(R, S), attendee(R, A), confirmed(R).
filled_raw(S, D, V, count(A)) :- seat(S, A), attendee_attr(A, D, V).
filled(S, D, V, F)          :- tracked(S, D, V), filled_raw(S, D, V, F).
filled(S, D, V, 0)          :- tracked(S, D, V), !filled_raw(S, D, V, _).
remaining(S, D, V, Hi - F)  :- target(S, D, V, _, Hi), filled(S, D, V, F).
gap(S, D, V, Lo - F)        :- target(S, D, V, Lo, _), filled(S, D, V, F), Lo - F > 0.
full(S, D, V)               :- remaining(S, D, V, R), R <= 0.
imbalance(S, D, B, Fa - Fb) :- ratio_target(S, D, A, B, Max), filled(S, D, A, Fa), filled(S, D, B, Fb), Fa - Fb > Max.
```

- **취소 = 자리 반환.** 두 가지 표현을 모두 지원한다: (a) `status_event`에 `cancelled`가 가장 최근으로 들어오면 `confirmed(R)`이 사라진다. (b) 신청 사실을 `remove`하면(철회) 같은 결과가 증분으로 나온다. 테스트는 둘 다 확인한다.
- `pending_payment`는 `filled`에 넣지 않고 `pending(S, D, V, N)`으로 따로 낸다.
- `unknown` 값은 `tracked`가 아니므로 목표 집계에서 빠지고, `needs_review(S, R, reason)`로 운영자에게 올라간다. 단, 사람 수이므로 `session_filled`에는 들어간다.

## 7. 홍보 판단 (③, `rules/promotion.dl`)

```
active(S)                            :- days_left(S, Days), Days >= 0.
recent(S, D, V, N)                   -- 최근 7일 안에 확정된 참가자 수 (없으면 0)
promote(S, D, V, G, "lead_time")     :- gap(S, D, V, G), active(S), !session_full(S),
                                        days_left(S, Days), policy(S, "lead_days", L), Days <= L.
promote(S, D, V, G, "slow_trend")    :- gap(S, D, V, G), active(S), !session_full(S),
                                        recent(S, D, V, N), policy(S, "trend_min_per_week", M), N < M.
promote(S, D, V, Diff, "imbalance")  :- imbalance(S, D, V, Diff), active(S), !session_full(S).
blocked(S, D, V, G, "session_full")  :- gap(S, D, V, G), active(S), session_full(S).
```

| 이유 | 뜻 | 권고 문구(사용자) |
|---|---|---|
| `lead_time` | 회차가 `lead_days` 안으로 다가왔는데 부족분이 남음 | "회차 임박, {value} {n}명 홍보 필요" |
| `slow_trend` | 최근 1주 확정 수가 `trend_min_per_week`보다 적음 | "신청 추세 느림, {value} {n}명 홍보 권장" |
| `imbalance` | 비율 목표의 허용 차를 넘음 | "{value} 쪽 {n}명 부족(비율)" |
| `blocked: session_full` | 부족분은 있으나 정원이 찼음 (지난 회차는 제외) | "정원 마감 — 목표와 정원이 충돌, 운영자 확인" |

**가정값** (운영사 정책이 정해지면 `policy/events/*.yaml`만 바꾼다): `lead_days: 7`, `trend_min_per_week: 3`, 비율 `max_diff: 1`.
한 (회차, 속성, 값)에 이유가 여럿이면 `Decision` 하나에 이유 목록으로 모은다. `need`와 문구는 우선순위(`lead_time` > `slow_trend` > `imbalance`)가 가장 높은 이유의 값을 쓴다 — 부족분(gap)과 비율 차(diff)는 다른 수이므로 섞지 않는다.
값 하나의 `lo`·`hi`가 정원보다 크면 입력 오류로 거부한다(`policy.py`). 여러 값의 `lo` 합이 정원을 넘는 것은 허용하며, 그 충돌이 `blocked`로 드러난다. 같은 값에 `promote`와 `blocked`가 동시에 나올 수는 없다 (`!session_full` / `session_full`로 갈린다).

## 8. 보안 · 데이터

- 저장소에는 **합성 데이터만** 둔다 (`data/synthetic/`). 실제 데이터는 `data/private/`(gitignore)에만 두고 LLM에 보내지 않는다.
- 모델에 개인 식별 칸이 없다 (3절). 시나리오 파일의 id는 `r1`, `s1` 같은 합성 id다.
- 운영사 이름 · 고객 코드 · 내부 문서는 저장소 어디에도 적지 않는다. 정책 파일의 예시 모임 이름도 합성이다.
- 비밀값은 환경변수로만. `.env.example`에는 이름만 ([standards/security-standards.md](standards/security-standards.md)).
- 엔진 출력 · 로그에는 참가자 id와 집계 숫자만 나온다.

## 9. wirelog 0.70.0 제약과 우회 (2026-10-29 Intel Mac 검증)

| 제약 (사실) | 우회 |
|---|---|
| 본문에서 `G = Lo - F` 같은 변수 바인딩은 오류 없이 **빈 결과**를 낸다 | 산술은 head에 쓴다: `gap(S, D, V, Lo - F) :- ..., Lo - F > 0.` 필요하면 중간 관계로 나눈다 |
| `min` `max` `count` `sum`은 열 이름으로 못 쓴다 (파싱 오류) | 목표 열은 `lo` · `hi` |
| PyreWire는 Python에서 intern하지 않은 symbol을 되돌리지 못한다 (`.dl` 안의 상수 · head 상수는 정수 id로 나옴) | `engine.py`가 규칙 파일의 따옴표 상수를 미리 `intern`하고, 데이터 사실은 모두 Python에서 `insert`한다 |
| `EasySession.snapshot`은 입력 관계(EDB)에 빈 결과를 돌려준다 | `engine.py`가 넣은 사실을 함께 보관하고 입력 관계는 거기서 읽는다 |
| `BatchProgram`은 inline 사실을 자동 적재하므로 `load_all_facts()`를 또 부르면 두 배로 센다. 결과 symbol도 id로만 나온다 | `EasySession`만 쓴다. `.dl`에 데이터 사실을 쓰지 않는다 |

검증 스크립트: `scripts/verify_wirelog.py` (25건 중 24건 통과, 실패 1건은 위 첫 줄의 기록용).

## 10. 저장소 구조

```
rules/            ontology.dl  capacity.dl  promotion.dl      (triage.dl은 다음 PR)
policy/events/    synthetic-example.yaml                      속성 정의 · 목표 · 홍보 기준(가정값)
src/event_ops_engine/
                  model.py bands.py clock.py facts.py policy.py   lib
                  engine.py                                       services
                  capacity.py promotion.py cli.py                 features
data/synthetic/scenarios/   single.yaml pair-mixed.yaml group.yaml ratio.yaml boundary.yaml
tests/            test_bands.py test_facts.py test_policy.py test_capacity.py test_promotion.py
scripts/          build-wirelog.sh  verify_wirelog.py
docs/             design.md glossary.md decisions/ standards/
```

## 11. 테스트 전략

- 계산 로직은 같은 PR에 단위 테스트를 올린다 ([standards/testing-standards.md](standards/testing-standards.md) 1번).
- lib 모듈은 순수 함수 테스트. 규칙은 시나리오 5개(1인 · 2인 혼성 · 단체 · 1:1 비율 · 경계)를 엔진에 넣고 파생 관계와 `Decision`을 확인한다.
- 취소는 (a) 상태 이력 (b) 사실 철회 두 경로를 모두 테스트한다.
- 엔진 라이브러리: `WIRELOG_LIB`가 비어 있고 `vendor/wirelog/build/libwirelog.1.dylib`가 있으면 `tests/conftest.py`가 자동으로 잡는다. 둘 다 없으면 wheel에 든 엔진을 쓴다(Linux CI).

## 12. 확인하지 못한 것

- 수백 건 이상 신청에서의 속도 — 합성 데이터는 회차당 20명 이하다.
- `average` 등 다른 집계 함수 — 이번 규칙은 `count` · `max`만 쓴다.
- 실제 운영사 정책값 — 7절의 값은 모두 가정값이다.

## 기록

| 날짜 | 내용 |
|---|---|
| 2026-10-29 | 처음 만듦 (핸드오프 §2~§6 + 문법 검증 결과 반영) |
| 2026-10-29 | PR #1 리뷰 반영: 이유 우선순위, 지난 회차 `blocked` 제외, 목표가 정원을 넘으면 거부 |
| 2026-10-29 | Linux CI(ubuntu, pyrewire 1.1.3 manylinux wheel 엔진)에서 테스트 60개 통과 확인 → 12절에서 제거 |
