# 설계 — 모임 운영 판단 엔진 (event-ops-engine)

회차별 신청 데이터를 **속성별 목표**와 견주어 현황을 내고, 홍보가 필요한지 판단하는 규칙 엔진이다.
규칙은 wirelog(Datalog)로 쓰고, Python은 입력을 사실(fact)로 바꾸고 결과에 근거를 붙이는 일만 한다.
용어는 [glossary.md](glossary.md)를 따른다. 결정 기록은 [decisions/](decisions/)에 있다.

## 1. 범위

| 모듈 | 하는 일 | LLM | 이번 PR |
|---|---|---|---|
| ② 현황 (capacity) | 회차 · 속성 값마다 `filled` · `gap` · `remaining` · 입금 대기 · 정원 대비 남은 자리 | 없음 | 구현 |
| ③ 홍보 판단 (promotion) | 부족분 · 남은 날 · 최근 추세 · 비율 불균형으로 홍보 **권고** 또는 **보류** | 없음 | 구현 |
| ① 운영 문의 판정 (triage) | 문의 글을 유형으로 해석(LLM) → 규칙으로 판정 → accept / ask / abstain / reject | 있음 | 계약 · 해석기 · 하네스 · 유형 1 · 2(13절). 유형 3~ 는 #18~#21 |

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
| services | `engine.py` `interpreter.py` `normalizer.py` | PyreWire를 감싼다. wirelog 제약(9절)을 여기서 모두 흡수한다. LLM 호출(Claude Code CLI · 가짜)도 여기 |
| features | `capacity.py` `promotion.py` `harness.py` `cli.py` | 사실 적재 → 스냅샷 → `Decision` · `Verdict` 조립 |

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
| `given_attr(attendee, dim, value)` | 입력에서 바로 아는 참가자 속성 (성별 · 나이 구간, 정규화 없는 직군은 `unknown`) | `facts.py` + `bands.py` |
| `candidate_attr(attendee, dim, value, confidence, evidence)` | 정규화기가 제안한 속성 후보 (확신도 0~100) | `facts.py` ← `normalizer.py` |
| `normalize_threshold(dim, min_pct)` · `dimension_value(dim, value)` | 후보를 받아들이는 기준과 허용 값 | 정책 `dimensions.job_group` |
| `attendee_attr(attendee, dim, value)` | 참가자 속성 (**파생**: `given_attr`이거나 기준 이상 후보, 14절) | `capacity.dl` |
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
rules/            ontology.dl  capacity.dl  promotion.dl  triage.dl
policy/events/    synthetic-example.yaml synthetic-job-group.yaml   속성 정의 · 목표 · 홍보 기준(가정값)
src/event_ops_engine/
                  model.py bands.py clock.py facts.py policy.py loader.py decision.py   lib
                  engine.py interpreter.py normalizer.py                              services
                  capacity.py promotion.py harness.py cli.py                          features
data/synthetic/scenarios/   single.yaml pair-mixed.yaml group.yaml ratio.yaml boundary.yaml job-group.yaml
                            triage/  account-length.yaml account-missing-entry.yaml
                                     delivery-timeout.yaml delivery-no-receipt.yaml
                                     duplicate-reregistration.yaml deadline-expired.yaml
                                     bug-confirmed-without-payment.yaml seat-full.yaml
                                     delivery-unreachable.yaml
tests/            test_<module>.py (lib · 규칙 · CLI · 해석기 · 문의 판정) test_readme.py (README 출력 예시 대조)
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

## 13. 운영 문의 판정 (①, `rules/triage.dl`, `harness.py`)

담당자의 "이거 버그인가요?"를 **LLM 출력 → 후보 사실 → 규칙 → 검증된 결정**으로 처리한다. 하네스 5단계를 모두 쓴다.

| 단계 | 하는 일 | 코드 |
|---|---|---|
| ADAPT | 질문 + 회차 · 신청(②와 같은 시나리오) + 이벤트 로그를 사실로 적재 | `facts.py` (`log_event` · `log_attr` · `question` · `supported_topic`) |
| INTERPRET | 해석기가 질문을 **후보 사실**로 바꾼다. 검증에 실패하면 여기서 `reject` | `interpreter.py` (Claude Code CLI · 가짜) |
| REASON | 후보 사실을 엔진에 넣고 규칙이 `in_scope` · `cause` · `needs`를 파생 | `rules/triage.dl` + 유형별 규칙 |
| DECIDE | 결정 계약(아래)으로 `Verdict` 조립 | `harness.py` |
| ACT | 결과 · 근거 · 단계별 trace 출력. 실행 없음(dry-run, 사람 확인) | `harness.py` · CLI |

**후보 사실** (`CandidateFact`): `relation`, `args`, `provenance(source, quote)`, `confidence`(0~1).
- `relation`은 후보 관계 다섯 개 중 하나만: `asks_about(q, topic)` · `about_registration(q, reg)` · `about_session(q, session)` · `about_event(q, log_id)` · `about_value(q, dim, value)`. 그 밖의 관계는 LLM이 **새 사실을 만든 것**이므로 `reject`.
- `provenance.quote`는 질문 원문의 일부여야 한다. `args`가 가리키는 신청 · 회차 · 로그 id · 속성 값(정책의 `dim=value`)이 입력에 없으면 `reject` ("로그에 없는 사실").
- 해석기는 사실을 **제안**만 한다. 원인 판정은 규칙만 한다.

**이벤트 로그** (`LogEvent`): `id`, `at`, `kind`, `registration`(선택), `attrs{key: value}`. 종류(`kind`)와 속성은 유형 규칙과 함께 정한다 (#15~#21). 합성 로그만 둔다.

**결정 계약** (`Verdict`, glossary "판정"):

| 조건 | 판정 | 내용 |
|---|---|---|
| 검증 실패 (관계 아님 · 근거 없음 · 없는 id) | `reject` | 거부 이유 |
| 지원하지 않는 주제 (`in_scope` 없음) | `abstain` | 지원 주제 목록 |
| 원인 1개 (`cause` 한 가지) | `accept` | 원인 + 근거 로그 id |
| 원인 0개, 범위 안 | `ask` | `needs`가 말하는 더 필요한 사실 |
| 원인 2개 이상 | `ask` | 후보 원인 목록, 사람이 가린다 |

```
in_scope(Q)      :- asks_about(Q, T), supported_topic(T).
cause(Q, C, E)   -- 유형 규칙이 파생. C는 원인 이름, E는 근거 로그 id
needs(Q, What)   -- 유형 규칙이 파생. 원인을 가리기 위해 더 필요한 사실
```

지원 주제(`supported_topic`)는 `payment` · `delivery` · `duplicate` · `deadline` · `seat` 다섯 개이고, 유형 규칙이 붙을 때마다 실제로 판정되는 주제가 늘어난다. 모든 `Verdict`에는 근거 id가 1개 이상 붙는다 (후보 사실 id `candidate/<q>/<relation>/<args>`, 로그 id `log/<id>`, 로그 하나로 설명되지 않는 원인은 규칙이 파생한 사실 이름 `rule/<name>`).

**질문 대상** (`subject(q, reg)`): 질문이 신청을 직접 가리키거나(`about_registration`) 그 신청의 로그 이벤트를 가리키면(`about_event`) 유형 규칙은 같은 신청을 본다.

**유형 규칙** (`rules/triage.dl`, 주제별로 붙는다):

| 유형 | 주제 | 보는 로그 (`kind` · `attrs`) | 원인 (`cause`) | 근거 | 더 필요한 사실 (`needs`) |
|---|---|---|---|---|---|
| 1 사용자 입력 실수 (#15) | `payment` | `account_issued{digits}` · `account_entered{digits}` | **가장 최근** 발급과 **가장 최근** 입력의 자릿수가 다르면 `user_input` (`superseded`로 이전 이벤트 제외) | 두 이벤트 id | `account_issued`가 없으면 그것, 있는데 `account_entered`가 없으면 그것 |
| 2 외부 요인 (#16) | `delivery` | `message_sent{result: timeout}` · 그 뒤의 전달 증거 `provider_receipt{result: delivered}` 또는 `provider_lookup{result: found}` (둘 사이에 재발송이 없을 때, `resent_between`) | `external_delay` (실제 전달됨, 재발송 불필요) | 발송 · 증거 id | 증거도 조회도 없으면 `provider_lookup` |
| 2b 외부 연결 실패 (#47) | `delivery` | `message_sent{result: timeout}` · 그 뒤의 `provider_lookup{result: none}`, 전달 증거 없음 | `external_failure` (업체에 닿지 못함, 재발송) | 발송 · 조회 id | 같음 |
| 3 정책상 정상 (#18) | `duplicate` | `registration_submitted{participant}` (질문 대상과 같은 회차의 다른 신청) | 같은 회차에 같은 참가자 키가 둘이면 `policy_normal` | 두 제출 이벤트 id | 질문 대상에 제출 기록이 없으면 `registration_submitted` |
| 4 기한 만료 (#19) | `deadline` | `payment_due`(가장 최근) · `payment_attempt{result: rejected}` | 거절된 시도 시각 > 기한 + `grace_minutes`이면 `expired` (은행이 받아 준 시도는 제외) | 기한 · 시도 id | 둘 중 없는 것 |
| 5 버그 의심 (#20) | 주제 무관 (`in_scope`이면) | 불변식 세 개: 확정인데 `payment_received` 없음 · `payment_received`가 최신 기한 + `grace_minutes` 뒤 · 확정 참가자의 속성 값이 ② `over_capacity` | `suspected_bug` | `rule/<불변식 이름>` | — (사람이 본다) |
| 6 자리 문의 (#21) | `seat` | 후보 사실 `about_session` · `about_value` + ② `full` · `over_capacity` | 마감이면 `seat_full`, 초과면 `over_capacity` (하나만) | `rule/full` · `rule/over_capacity` + 후보 사실 id | 회차 · 속성 값이 없으면 `session` · `attribute_value`, 그 값에 목표가 없으면 `target` |

`triage_policy(key, n)`은 유형 규칙의 정책값(`policy/events/*.yaml`의 `triage:`, 가정값). 지금은 `grace_minutes` 하나다. 참가자 키(`participant`)는 합성 식별자이며 실명 · 연락처를 두지 않는다. 유형 5의 `over_capacity` 근거는 불변식 이름뿐이라 어느 속성 값이 초과인지는 `event-ops report`로 본다(규칙 안에서 문자열을 만들 수 없어서, 9절). 유형 5 때문에 문의 시나리오의 확정 신청에는 `payment_received` 로그가 있어야 한다(없으면 그 신청에 대한 모든 문의가 `suspected_bug`). 같은 질문에 유형 5와 다른 유형이 함께 걸리면 원인이 둘이라 `ask`가 되고, 이것은 의도한 동작이다. `needs` 값에는 확인 주체가 붙어 나온다(`harness.NEEDS_VERIFIER`: 외부 = 발송 업체 로그, 내부 = 관리자 기록, 질문 = 묻는 사람, 정책). 관리자 알림의 '실패'는 보수적인 메모이고 전달 여부의 진실은 업체 로그라서다(운영 자료 T0551 · T0583). 원인이 하나라도 파생되면 `needs`는 비운다 (다른 이벤트의 '아직 없는 사실'이 확정된 원인에 끌려 나오지 않게). 자릿수가 같거나 수신증이 `failed`이면 원인도 `needs`도 없어 `ask`가 된다. 그 경우는 아직 유형이 없다는 뜻이고, #18~#21에서 유형이 늘면 거기서 판정된다. 시나리오 파일은 `expected`(기대 판정 · 원인 · needs)를 적고, `event-ops triage`는 실제 판정과 비교해 다르면 종료 코드 1을 낸다. `cause` · `needs`를 비우면(null) 비교하지 않고, `needs: []`는 '더 필요한 사실 없음'을 단언한다.

**해석기**: 기본은 Claude Code CLI(`claude -p`, 구독 안 · 추가 비용 0), 테스트는 가짜 해석기(시나리오 파일의 `canned` 응답). API는 쓰지 않는다. LLM 출력은 JSON이며 `Interpretation` 모델 검증을 통과해야 한다.

## 14. 속성 정규화 (`job_group`, `normalizer.py`, `capacity.dl`)

자유 입력(예: "백엔드 3년차")을 정책의 범주 값 중 하나로 바꾼다. ①과 같은 원칙이다: **LLM은 제안만, 규칙이 받아들인다.**

| 단계 | 하는 일 | 코드 |
|---|---|---|
| 정책 | `dimensions.job_group: { values: [...], normalize: llm, min_confidence: 0.7 }` (기준값은 가정값) | `model.py` `JobGroupDimension` |
| 정규화 | 신청자의 `job` 문구마다 정규화기가 `NormalizedValue(value, confidence, quote)`를 제안. `quote`가 문구에 없거나 답이 없으면 `unknown` · 확신도 0 | `normalizer.py` `normalize_members` (Claude Code CLI · 가짜) |
| 사실 | 후보는 `candidate_attr(attendee, job_group, value, 확신도%, job/<attendee>)`, 문구가 없으면 `given_attr(…, job_group, unknown)`. 확신도는 1% 해상도로 **내림**(0.695는 0.7 기준을 넘지 못한다) | `facts.py` |
| 규칙 | 확신도 ≥ 기준이고 값이 허용 목록에 있으면 `attendee_attr`로 올린다. 기준 미만이면 `unknown` + `needs_review(…, "low_confidence")`, 목록 밖 값이면 `unknown` + `needs_review(…, "unknown_value")`. 네 규칙은 서로 배타적이라 참가자마다 값이 하나다(wirelog는 중복을 남기므로 `count`가 두 번 셀 수 있다) | `capacity.dl` |
| 결과 | ② 현황이 `job_group` 목표를 보통 속성처럼 계산하고, 확인 요청에 근거 `job/<attendee>`가 붙는다 | `capacity.py` |

`attendee_attr`는 이제 파생 관계다(wirelog는 한 관계에 입력과 규칙을 섞지 못한다, 9절). 입력은 `given_attr`로 들어온다. `event-ops report --normalizer claude`(triage도 같은 옵션)가 실제 CLI를 쓰고, 기본 `fake`는 시나리오의 `canned_job_groups`를 쓴다. `job` 문구는 합성이며 이름 · 연락처를 두지 않는다(8절).

## 기록

| 날짜 | 내용 |
|---|---|
| 2026-10-29 | 처음 만듦 (핸드오프 §2~§6 + 문법 검증 결과 반영) |
| 2026-10-29 | PR #1 리뷰 반영: 이유 우선순위, 지난 회차 `blocked` 제외, 목표가 정원을 넘으면 거부 |
| 2026-10-29 | Linux CI(ubuntu, pyrewire 1.1.3 manylinux wheel 엔진)에서 테스트 60개 통과 확인 → 12절에서 제거 |
| 2026-10-31 | 13절 ① 운영 문의 판정: 하네스 5단계, 후보 사실, 결정 계약, 해석기 |
| 2026-10-31 | 13절 유형 1 · 2 규칙, 질문 대상, 기대 판정 (#15 · #16 · #17) |
| 2026-11-02 | 1절 · 10절을 ① 구현 이후 상태로 갱신 (#26) |
| 2026-11-02 | 13절 유형 3 · 4 규칙, `triage_policy` (#18 · #19) |
| 2026-11-02 | 13절 유형 5 · 6 규칙, 후보 관계 `about_value`, 근거 `rule/<name>` (#20 · #21) |
| 2026-11-02 | 14절 속성 정규화(`job_group`), 5절 `given_attr` · `candidate_attr`, `attendee_attr` 파생으로 (#22~#25) |
