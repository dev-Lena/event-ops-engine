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

CLI 출력은 두 가지다. 기본은 운영자가 읽는 한국어 문장이고, `--json`은 다른 시스템이 읽는 구조다(#85). JSON은 `schema`(`event-ops/report@1` · `event-ops/triage@1`)로 버전을 밝힌다. 성별 결정에 묶인 조합 몫은 `Decision.parts`에 담는다(#32). 비슷한 나잇대 모임의 성별 · 묶음별 나이는 회차의 `ages`, 범위 제안은 `range_suggestions`에 담는다(#91, 나이 · 범위와 수만). 필드를 **더하는** 것은 같은 번호로 두고(읽는 쪽은 모르는 필드를 무시한다), 필드를 바꾸거나 없애면 번호를 올린다(#32에서 정함). `Decision` · `Verdict`는 pydantic 모델을 그대로 직렬화해 문장 출력과 같은 판단 · 근거를 담는다. 형식 예시는 README "결과 JSON".

계층 (공용 코드 기준 1번, [CONTRIBUTING.md](../CONTRIBUTING.md)):

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
  sessions: [Session]            # id, date, capacity, targets · combos · similar_age 덮어쓰기(선택),
                                 # start_time "HH:MM"(서울 시각, 선택), lead_days · promotion_cutoff_hours 덮어쓰기(선택)
  registrations: [Registration]  # id, session_id, members | party_size, status_events

Registration
  members: [Member] | None       # 참가자 목록. None이면 구성 미상(옛 신청)
  party_size: int                # members가 있으면 len과 같아야 한다
  status_events: [StatusEvent]   # (ts, status) — status는 glossary "상태 값" 다섯 개만
  attrs: {속성: 값}               # per: registration 선택 속성의 답 (예: mode)
  pair: female_pair | male_pair | mixed_pair | None   # 신청폼에서 고른 2인 유형 (4절)
Member
  gender: female | male | unknown
  birth_year: int | None
  attrs: {속성: 값}               # per: member 선택 속성의 답 (예: region)
```

**선택 속성 (#31)**: 신청폼에서 정해진 목록 중 고르는 속성(지역, 참여 방식)은 정책 `dimensions.choices`에 이름 · 값 목록 · 단위(`per: member`(기본) | `registration`)로 선언한다. 답은 신청이나 참가자의 `attrs`에 적고, `facts.py`가 그대로 `given_attr`로 넣는다. 정규화하지 않으며 규칙은 바꾸지 않는다(계산은 이미 속성 일반형). `per: registration`이면 함께 신청한 사람 모두 같은 값이다. 답이 없으면 `unknown`이라 목표 집계에서 빠진다(성별 미상과 같음). 목록 밖 값, 선언하지 않은 속성 이름, 단위가 틀린 자리의 답은 모델이 거부한다. 그래서 `attrs`에는 자유 서술이 들어올 수 없다. 함께 고친 것: 목표 · 비율이 정책에 선언하지 않은 (속성, 값)을 가리키면 전에는 오류 없이 받아들여 계속 "부족"으로 나왔다. 이제 정책 · 시나리오를 읽을 때 거부한다. 예시: `policy/events/synthetic-hybrid.yaml`, `data/synthetic/scenarios/hybrid.yaml`.

**조합 목표 (#32)**: "25~29세 여성 4명"처럼 성별 하나와 나이 범위를 묶은 목표다. 운영사 확인(2026-11-09, 사용자 설명): 신청 때 출생연도를 받고 2인 신청의 동반자 것도 받으며 필수 입력이다. 참가자 구성(성별)을 모르는 신청은 없다. 성별 × 나이로 모집 목표를 두는 모임이 많고, 광고도 성별 × 나이로 나눠 집행한다. 나이를 관리하지 않는 모임도 있고, 나이가 중요한 모임은 10년 단위가 아니라 25~29세처럼 잘게 쓰며 단위는 모임마다 다르다.

- 정책 `defaults.combos`에 `<id>: { gender, age: [하한, 상한] }`으로 적고, 회차의 `combos`가 id 단위로 더하거나 바꾼다. 담당자가 신청 현황을 보고 회차마다 정하기 때문이다. 목표는 `targets.combo.<id>`. 회차의 `targets.combo`는 다른 속성처럼 기본 조합 목표를 **통째로** 바꾼다(회차가 조합 하나에만 목표를 두면 기본 조합의 목표는 그 회차에서 빠진다). 나이 구간(`age_band`)을 쓰지 않는 이유: 구간은 모임마다 한 벌뿐이고, 어느 구간에도 들지 않는 나이는 `unknown`이 된다.
- 나이는 나이 구간과 같이 연 나이(회차 연도 − 출생연도)다. 출생연도만 받으므로 만 나이는 정확히 알 수 없고, 출력에 "연 나이"로 밝힌다. 광고 플랫폼이 만 나이를 쓰면 경계에서 1살 어긋날 수 있다.
- 입력 검사: 성별은 `unknown`이 아니고 `0 ≤ 하한 ≤ 상한`. 같은 성별 조합끼리 나이 범위가 겹치면 거부한다(한 사람이 두 조합에 들어 필요 인원 합계가 틀린다). 정의하지 않은 조합을 가리키는 목표, 조합에 거는 비율 목표(신청폼을 닫는 단위는 성별, 운영 자료 T0316 · T0375)도 거부한다. 회차마다 한 성별의 조합 최소 인원 합이 그 성별의 최대 인원(목표가 없으면 정원)을 넘으면 거부한다(`policy.py`).
- 출생연도가 빠진 참가자는 데이터 오류다. 나이를 읽는 모임(나이 구간이나 조합이 있음)에서는 `needs_review(…, "missing_birth_year")`로 올리고 나이 집계에서 뺀다. 성별 집계에는 들어간다.
- 나이가 중요한 모임은 나이를 조합으로만 적기를 권한다. 단독 나이 구간 목표와 같이 쓰면 두 목표가 따로 판단된다(막지는 않는다).
- 현황에서 조합은 그 성별 줄 아래에 나이 순으로 나온다. 홍보 권고도 성별 한 줄에 묶어 낸다(7절). 따로 내면 "여성 2명 부족" + "25~29세 여성 1명 부족"이 3명으로 읽히기 때문이다.
- 예시: `policy/events/synthetic-age-combos.yaml`, `data/synthetic/scenarios/combo.yaml`.

**비슷한 나잇대 (#91 A · B · C, 결정 기록: [decisions/2026-11-10-similar-age.md](decisions/2026-11-10-similar-age.md))**: 운영사 확인(2026-11-09, 사용자 설명): 나이가 중요한 모임은 "비슷한 나잇대"를 미리 정하지 않는다. 담당자가 신청 현황을 보고 정하고, 보통 10~15살 차이 이내다. 사용자 결정(2026-11-09 · 10): 폭은 성별마다 잰다. 정한 범위는 신청자 선별, 광고 대상 나이, 조합 목표 인원에 쓰인다.

- 정책 맨 위에 `similar_age: {}`를 두면 그 모임의 `report`가 성별마다 나이 목록과 폭(가장 많은 나이 − 가장 적은 나이, 연 나이)을 보인다. 나이를 관리하지 않는 모임이 있어서 켜는 방식이다. 조합을 켜는 조건으로 쓰지 않는 이유: 범위를 정하기 전, 곧 조합을 적기 전이 가장 필요한 때다.
- `similar_age:`처럼 값을 비우면 YAML이 null로 읽어 조용히 꺼지므로, 정책을 읽을 때 거부한다(`loader.py`). 모델에서 막지 않는 이유: `model_dump`한 정책이 `similar_age: None`을 담아 다시 검증되지 않는다.
- 두 묶음을 따로 보인다. **확정·대기**(자리를 차지한 사람, 그 자리에 올 사람)와 **신청 접수**(`applied`, 담당자가 아직 고르는 사람)다. 선별을 돕는 것은 신청 접수 줄이다.
- 사람을 가리키지 않는다. 출력(문장 · JSON)에는 나이와 수만 있고 신청 id나 "범위 밖" 표시는 없다. 엔진은 개별 신청자를 거절하지 않는다(1절). 나이는 작은 순으로 적어 신청 순서와 이어지지 않게 한다.
- 출생연도가 없거나 회차 연도보다 늦은 참가자는 목록에서 빠지고 그 수를 "출생연도 없음·오류 N명 제외"로 붙인다. 목록이 성별 인원보다 짧은 이유가 보이게 하려는 것이다. `similar_age`를 둔 모임도 나이를 읽는 모임이라, 자리를 차지한 사람의 출생연도가 없으면 지금처럼 `missing_birth_year` 확인 요청이 나온다.
- 현황에서 나이 줄은 그 성별 줄 바로 아래, 조합보다 먼저 나온다. 성별 줄이 없는 성별(목표가 없음)은 맨 위 줄에 성별 이름을 붙여 나온다.
- **폭 확인 요청 (#91 B)**: `similar_age: { max_spread: N }`을 두면, 어떤 성별의 확정·대기 폭이 N보다 **클 때** 확인 요청을 낸다("N살 차이 이내"이므로 같으면 괜찮다). 회차는 `similar_age: { max_spread: M }`으로 덮어쓴다. 기준이 없으면 나이만 보이고 확인 요청은 없다. 회차만 `similar_age`를 켤 수는 없다(모임 단위 결정이라서). 기준값은 **가정값**이다. 운영사 설명 "보통 10~15살"은 모임별 값이 아니다.
  - 신청 접수는 세지 않는다. 아직 고르지 않은 사람 때문에 경고하지 않고, 선별 뒤 검사로 둔다("신청 접수까지 모두 받으면" 표시는 사용자가 넣지 않기로 함, 2026-11-10). 지난 회차에도 내지 않는다.
  - 기존 `needs_review(회차, 신청, 이유)`는 신청 단위라서 쓰지 않는다. 쓰면 폭을 넓힌 사람을 가리키게 된다. 회차 × 성별 관계 `age_spread_review`를 따로 두고, `report`의 "확인 요청" 줄과 JSON `needs_review`에 `Decision`(`kind: ask`, `dim: gender`, `reasons: [age_spread]`)으로 나온다. 근거는 신청 id가 아니라 `similar_age/<회차>` · `age_spread_limit/<회차>`다.
- **범위 제안 (#91 C)**: 폭 기준이 있는 모임에서, 조합이 아직 없는 성별마다 기준 폭의 범위 중 확정·대기가 가장 많이 드는 것을 제안한다. 문구에 "지금 확정·대기 기준"을 밝히고, 고른 범위를 조합으로 적으면 기존 조합 권고가 광고 대상을 낸다(7절). 사용자 결정(2026-11-10) 세 가지:
  - **가운데 맞춤**: 든 사람들(가장 어린 ~ 가장 많은 나이)을 범위 가운데에 둔다. 남는 해가 홀수면 한 해는 나이 많은 쪽으로 간다. 예: 26 · 28 · 28, 폭 12 → 21~33세. 아무도 없는 나이까지 넓혀질 수 있다(운영사의 최소 나이 기준은 확인하지 않음).
  - **동점이면 후보를 모두** "또는"으로 보인다. 엔진이 근거 없이 하나를 고르지 않는다.
  - **조합이 있는 성별에는 내지 않는다.** 제안은 조합을 적도록 돕는 것이고, 적은 뒤에는 조합 줄이 범위 안팎을 보인다.
  - 신청 접수는 세지 않고, 지난 회차에는 내지 않는다. 범위 계산은 규칙(`range_suggestion`)이 하고, 출력에는 범위와 수만 있다.
- 예시: `policy/events/synthetic-similar-age.yaml`, `data/synthetic/scenarios/similar-age.yaml`.

개인 식별 정보 칸은 **모델에 없다**. 이름 · 연락처 · 계좌 · 자유 서술은 들어올 자리가 없으므로 실수로도 저장소 · 출력에 섞이지 않는다.

## 4. 인원 환산

정원과 목표는 **사람 수**다. 신청 1건을 참가자 n명으로 펼친다 (`facts.py`).

| 신청 | 참가자 | 성별 속성 |
|---|---|---|
| 1인 | 1 | 신청자 성별 |
| 2인 같은 성별 (`pair: female_pair` · `male_pair`) | 2 | 둘 다 같은 값 |
| 2인 혼성 (`pair: mixed_pair`) | 2 | 1 + 1 |
| n명 단체 | n | 구성원마다 |
| 구성 미상 (옛 신청, `members: None`) | `party_size` | 모두 `unknown` → 목표 집계에서 빠지고 `needs_review`로 올라간다 |

참가자 id는 `<registration id>#<순번>`. 나이 구간은 `bands.py`가 `birth_year`와 회차 연도로 계산한다 (경계 규칙은 glossary). 조합이 있는 회차는 같은 계산의 나이를 `attendee_age`로 넣는다.

**자료와 일치** (#44 · #78): 운영 대화의 인원 계산 규칙(혼성 1건 = 남녀 각 1명, 같은 성별 2인 1건 = 그 성별 2명, T0468~T0473 · T0558)이 이 표와 같다. 다만 실제 시스템은 1인 회차와 2인 회차를 구분하지 못하므로, 연동할 때는 회차 유형을 입력으로 받아야 한다 (#35).

**2인 신청 유형 (#33)**: 신청폼에서 2인 신청은 여여 · 남남 · 혼성 중 하나를 고른다. 신청에 `pair`만 적으면 엔진이 그 성별의 참가자 2명으로 펼치고 출생 연도는 모르는 것으로 둔다(나이 구간 `unknown`, 나이 목표 집계에서 빠짐). 다만 실제 신청폼은 동반자 것까지 출생연도가 필수라서(운영사 확인 2026-11-09), 나이를 읽는 모임(나이 구간이나 조합이 있음)에서는 데이터 오류로 보고 `missing_birth_year` 확인 요청을 낸다(3절 조합 목표). 출생 연도를 알면 `members`를 함께 적고, 이때 성별 구성이 유형과 맞아야 한다(순서는 상관없음). 맞지 않거나 인원이 2명이 아니면 모델이 거부한다. 참가자별 선택 속성(예: 지역, 3절)도 받는다면 `members`에 성별과 `attrs`를 함께 적는다(유형만으로 펼친 참가자는 `attrs`가 없어 `unknown`). 동반자 정보를 자유 글에서 LLM으로 뽑는 원래 안은 폼이 유형을 고르게 하므로 하지 않았다. 예시: `data/synthetic/scenarios/pair-type.yaml`.

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
| `attendee_age(attendee, age)` | 연 나이 (조합이 있는 회차(#32)나 `similar_age` 모임(#91)만) | `facts.py` + `bands.py` |
| `similar_age(session)` | 비슷한 나잇대를 관리하는 모임의 회차 (#91) | 정책 `similar_age` |
| `age_spread_limit(session, years)` | 성별 확정·대기 폭의 기준 (회차 덮어쓰기 반영, 없으면 사실 없음, #91 B) | `policy.py` |
| `age_missing(attendee)` | 나이를 읽는 모임인데 출생연도가 없음 (데이터 오류) | `facts.py` |
| `combo_def(session, combo, gender, lo, hi)` | 회차의 조합: 성별 + 나이 범위 (양 끝 포함) | `policy.py` |
| `counted_attr(attendee, dim, value)` | 집계에 쓰는 속성 (**파생**: `attendee_attr` + 조합 `combo`) | `capacity.dl` |
| `target(session, dim, value, lo, hi)` | 속성 값 목표 | `policy.py` |
| `ratio_target(session, dim, value_a, value_b, max_diff)` | 비율 목표 | `policy.py` |
| `policy(session, key, n)` | 홍보 기준값 (회차 덮어쓰기 반영) | `policy.py` |
| `promotion_cutoff_ts(session, ts)` | 홍보 중단 시각 = 시작 시각 − `promotion_cutoff_hours` (시작 시각이 있을 때만) | `clock.py` |
| `earliest_cutoff_ts(session, ts)` | 시작 시각이 없을 때 홍보 중단이 가장 이르게 올 수 있는 시각 (회차 날 자정 − 시간) | `clock.py` |

## 6. 현황 규칙 (②, `rules/capacity.dl`)

```
latest_ts(R, max(T))        :- status_event(R, T, _).
current_status(R, St)       :- latest_ts(R, T), status_event(R, T, St).
confirmed(R)                :- current_status(R, "confirmed").
seat(S, A)                  :- registration(R, S), attendee(R, A), confirmed(R).
combo_hit(A, C)             :- combo_def(S, C, G, Lo, Hi), attendee_session(A, S),
                               attendee_attr(A, "gender", G), attendee_age(A, Age), Age >= Lo, Age <= Hi.
counted_attr(A, D, V)       :- attendee_attr(A, D, V).
counted_attr(A, "combo", C) :- combo_hit(A, C).
filled_raw(S, D, V, count(A)) :- seat(S, A), counted_attr(A, D, V).
filled(S, D, V, F)          :- tracked(S, D, V), filled_raw(S, D, V, F).
filled(S, D, V, 0)          :- tracked(S, D, V), !filled_raw(S, D, V, _).
remaining(S, D, V, Hi - F - P) :- target(S, D, V, _, Hi), filled(S, D, V, F), pending(S, D, V, P).
gap(S, D, V, Lo - F - P)    :- target(S, D, V, Lo, _), filled(S, D, V, F), pending(S, D, V, P), Lo - F - P > 0.
full(S, D, V)               :- remaining(S, D, V, R), R <= 0.
imbalance(S, D, B, Fa - Fb) :- ratio_target(S, D, A, B, Max), filled(S, D, A, Fa), filled(S, D, B, Fb), Fa - Fb > Max.
```

- **입금 대기도 자리를 차지한다.** 남은 자리 · 남은 목표 자리 · 부족분은 확정과 입금 대기를 모두 뺀 값이다 (운영사 규칙: 남은 자리 = 정원 − 확정 − 입금 대기, 운영 자료 T0455 · T0558). `filled`(확정)과 `pending`은 따로 보여 준다. 비율 불균형(`imbalance`) · 최근 추세 · 정원 초과(`over_capacity`)는 확정만 센다: 입금 대기로 `full`이 될 수는 있어도 `over_capacity`는 확정이 상한을 넘을 때만이다.
- **취소 = 자리 반환.** 두 가지 표현을 모두 지원한다: (a) `status_event`에 `cancelled`가 가장 최근으로 들어오면 `confirmed(R)`이 사라진다. (b) 신청 사실을 `remove`하면(철회) 같은 결과가 증분으로 나온다. 테스트는 둘 다 확인한다.
- `pending_payment`는 `filled`에 넣지 않고 `pending(S, D, V, N)`으로 따로 낸다.
- `unknown` 값은 `tracked`가 아니므로 목표 집계에서 빠지고, `needs_review(S, R, reason)`로 운영자에게 올라간다. 단, 사람 수이므로 `session_filled`에는 들어간다.
- 조합(#32)은 `combo`라는 속성 값처럼 센다. 확정 · 입금 대기 · 최근 추세 집계가 모두 `counted_attr`를 쓰므로 목표 · 부족 · 목표 충족 계산이 다른 속성과 같다. 같은 성별의 나이 범위는 겹치지 않으므로(3절) 한 사람은 성별마다 조합 하나에만 든다.
- 비슷한 나잇대(#91 A)는 성별 × 묶음마다 나이를 모은다. 묶음 `occupying`은 확정 · 입금 대기(`occupies`), `applied`는 신청 접수다. 폭은 `min` · `max` 집계와 head 산술로 낸다(9절 검증 3c). 규칙은 사람을 가리키는 관계를 내지 않고, 출력은 나이와 수만 쓴다(3절).

```
age_pool(R, "occupying")     :- occupies(R).
age_pool(R, "applied")       :- applied(R).
age_entry(S, G, P, A, Age)   :- similar_age(S), registration(R, S), age_pool(R, P), attendee(R, A),
                                attendee_attr(A, "gender", G), attendee_age(A, Age).
age_low(S, G, P, min(Age))   :- age_entry(S, G, P, _, Age).
age_high(S, G, P, max(Age))  :- age_entry(S, G, P, _, Age).
age_spread(S, G, P, Hi - Lo) :- age_high(S, G, P, Hi), age_low(S, G, P, Lo).
age_unknown_count(S, G, P, count(A)) :- age_unknown(S, G, P, A).   // 출생연도 없음 (age_missing)
age_spread_review(S, G, N, L) :- age_spread(S, G, "occupying", N), age_spread_limit(S, L), N > L,
                                 days_left(S, D), D >= 0.         // 폭 확인 요청 (#91 B)
// 범위 제안 (#91 C): 각 확정·대기 나이에서 시작하는 기준 폭 범위를 세고, 가장 많이 든 범위를 가운데 맞춤
window_count(S, G, Lo, count(A))  :- window_member(S, G, Lo, A).          // Lo ≤ 나이 ≤ Lo + W
window_slack(S, G, Lo, W - Hi + Lo) :- window_top(S, G, Lo, Hi), age_spread_limit(S, W).
range_suggestion(S, G, Lo - Sl / 2, Lo - Sl / 2 + W, N) :- window_count(S, G, Lo, N), best_window_count(S, G, N),
                                 window_slack(S, G, Lo, Sl), age_spread_limit(S, W), !gender_has_combo(S, G), …
```

## 7. 홍보 판단 (③, `rules/promotion.dl`)

```
active(S)                            :- days_left(S, Days), Days >= 0.
past_cutoff(S)                       :- promotion_cutoff_ts(S, T), now(N), N >= T, active(S).
cutoff_unknown(S)                    :- earliest_cutoff_ts(S, T), now(N), N >= T, active(S).
recent(S, D, V, N)                   -- 최근 7일 안에 확정된 참가자 수 (없으면 0)
promote(S, D, V, G, "lead_time")     :- gap(S, D, V, G), active(S), !session_full(S),
                                        days_left(S, Days), policy(S, "lead_days", L), Days <= L.
promote(S, D, V, G, "slow_trend")    :- gap(S, D, V, G), active(S), !session_full(S),
                                        recent(S, D, V, N), policy(S, "trend_min_per_week", M), N < M.
promote(S, D, V, Diff, "imbalance")  :- imbalance(S, D, V, Diff), active(S), !session_full(S).
blocked(S, D, V, G, "session_full")  :- gap(S, D, V, G), active(S), session_full(S).
cap(S, D, A, Fb + Max, B, Fb, Max) :- ratio_target(S, D, A, B, Max), filled(S, D, A, Fa), filled(S, D, B, Fb), Fa - Fb > Max, active(S), !session_full(S).   // 대칭 규칙도 있음
capped(S, D, V)             :- cap(S, D, V, _, _, _, _).   // promote 세 규칙은 !capped, !held, !past_cutoff
combo_gap_sum(S, G, sum(N)) :- gap(S, "combo", C, N), combo_gender(S, C, G).        // 조합 (#32)
gender_room(S, G, R)        :- remaining(S, "gender", G, R) | 성별 목표가 없으면 remaining_seats(S, R)
combo_conflict(S, G)        :- combo_gap_sum(S, G, N), gender_room(S, G, R), N > R.
held(S, "combo", C)         :- combo_gender(S, C, G), cap(S, "gender", G, …).        // 조용히
held(S, "combo", C)         :- combo_gender(S, C, G), combo_conflict(S, G).          // 보류로
blocked(S, "combo", C, N, "gender_room") :- gap(S, "combo", C, N), combo_gender(S, C, G),
                                            combo_conflict(S, G), active(S), !session_full(S).
```

| 이유 | 뜻 | 권고 문구(사용자) |
|---|---|---|
| `lead_time` | 회차가 `lead_days` 안으로 다가왔는데 부족분이 남음 | "회차 임박, {value} {n}명 홍보 필요" |
| `slow_trend` | 최근 1주 확정 수가 `trend_min_per_week`보다 적음 | "신청 추세 느림, {value} {n}명 홍보 권장" |
| `imbalance` | 비율 목표의 허용 차를 넘음 | "{value} 쪽 {n}명 부족(비율)" |
| `blocked: session_full` | 부족분은 있으나 정원이 찼음 (지난 회차는 제외) | "정원 마감 — 목표와 정원이 충돌, 운영자 확인" |
| `blocked: gender_room` | 한 성별의 조합 부족 합이 그 성별의 남은 자리보다 큼 (#32) | "목표 충돌: {성별} 조합 부족 합 {n}명이 남은 자리보다 많음, 운영자 확인" |

**기준값** (#52, 2026-11-06 결정. 바꿀 때는 `policy/events/*.yaml`만 바꾼다. 결정 기록: [decisions/2026-11-07-promotion-thresholds.md](decisions/2026-11-07-promotion-thresholds.md)):

| 기준 | 값 | 확인됨 / 가정 | 근거 |
|---|---|---|---|
| `promotion_cutoff_hours` | 2 (회차별 덮어쓰기) | **확인됨** | 운영사 확인: 모임 시작 2시간 전부터 홍보 중단. 실제 회차 설정 32개 모두 2시간 |
| `lead_days` | 7 (회차별 덮어쓰기) | 가정 | 운영사에 고정 기준이 없다는 것은 확인됨 (임박 기준이 그때그때 5~15일) |
| `trend_min_per_week` | 3 (직군 예시 2) | 가정 | 운영사의 광고 조건에 추세는 없다(확인됨). pace(같은 D-day 기대 확정률 대비 속도)로 바꾸는 것은 #75 |
| 비율 `max_diff` | 1 | 가정 | 홍보(`imbalance`)와 잠정 마감(`cap`)에 같은 값. 운영사의 성별 한도 방식은 확인 중 |

`imbalance` 홍보 권고는 기간 제한 없이 낸다(운영사는 임박했을 때 광고하지만, 엔진은 더 일찍 알리는 쪽을 택함).
한 (회차, 속성, 값)에 이유가 여럿이면 `Decision` 하나에 이유 목록으로 모은다. `need`와 문구는 우선순위(`lead_time` > `slow_trend` > `imbalance`)가 가장 높은 이유의 값을 쓴다 — 부족분(gap)과 비율 차(diff)는 다른 수이므로 섞지 않는다.

**조합 권고 (#32, 결정 기록: [decisions/2026-11-09-combination-targets.md](decisions/2026-11-09-combination-targets.md))**: 규칙은 조합도 다른 값처럼 `promote` · `blocked`를 내고, `promotion.py`가 그 행을 조합의 성별 결정 하나(`dim = gender`)로 묶는다. 조합 몫은 `Decision.parts`(조합 id · 표시 이름 · 부족 · 이유)에 담는다.
- `need` = max(성별 자신의 부족분, 그 성별 조합 부족의 합). 조합에 든 사람은 성별에도 세이므로 둘을 더하지 않는다. 비율 차(`imbalance`)는 부족분이 아니라서 이 계산에 넣지 않는다.
- 묶는 조합은 규칙이 권고(또는 보류)한 것만이다. 부족분이 있어도 임박 · 추세 조건에 걸리지 않은 조합은 성별과 마찬가지로 아직 권고하지 않는다.
- 문구는 광고 단위로 쓴다: "회차 임박: female 3명 부족, 홍보가 필요합니다. 광고 대상: female 25~29세(연 나이) 3명 이상." 성별 자신은 부족하지 않고 조합만 부족하면 조합 이름을 바로 쓴다("female 25~29세(연 나이) 1명 부족").
- 성별이 잠정 마감 중이면 그 성별의 조합 권고를 내지 않는다(잠정 마감 권고가 이유를 말한다). 홍보 중단(`past_cutoff`)과 정원 마감(`session_full`)은 다른 값과 같다.
- 조합 부족의 합이 그 성별이 더 받을 수 있는 자리(성별 목표의 남은 자리, 목표가 없으면 회차의 남은 자리)보다 크면 홍보로 함께 채울 수 없다. 그 성별의 조합은 권고 대신 `blocked(…, "gender_room")` 보류가 되고 운영자가 목표를 정한다(`session_full`과 같은 성격). 범위 밖 나이의 사람이 자리를 차지하면 생긴다. 같으면 충돌이 아니다.
- 이때 성별 자신의 부족분 권고는 그대로 낸다(조합 몫 없이). 그래서 조합이 묶인 성별에는 권고와 보류가 함께 나올 수 있다.
값 하나의 `lo`·`hi`가 정원보다 크면 입력 오류로 거부한다(`policy.py`). 여러 값의 `lo` 합이 정원을 넘는 것은 허용하며, 그 충돌이 `blocked`로 드러난다. 같은 값에 `promote`와 `blocked`가 동시에 나올 수는 없다 (`!session_full` / `session_full`로 갈린다). 예외는 위의 조합 충돌 보류다(성별 결정과 조합 보류가 따로 나온다).

**홍보 중단 (#52)**: 회차에 시작 시각(`start_time`, 서울 시각 `"HH:MM"`)이 있으면 시작 `promotion_cutoff_hours`시간 전부터 홍보 권고(`promote`의 세 이유)를 내지 않는다. 정확히 그 시각부터 멈춘다(경계 포함). 마감 시각은 `clock.py`가 계산해 `promotion_cutoff_ts`로 넣고, 규칙은 `now`와 비교만 한다(9절의 본문 산술 제약). 정원 충돌 보류(`blocked`)와 잠정 마감(`cap`)은 홍보가 아니므로 지금처럼 날짜 단위 `active`를 따른다. `event-ops report`는 마감이 지난 회차에 "홍보 중단" 줄을 보여, 부족분이 남았는데 "권고 없음"으로 읽히지 않게 한다. 시작 시각이 없으면 예전처럼 날짜 단위(당일까지)로 판단한다. 다만 마감이 이미 지났을 수 있는 때(`earliest_cutoff_ts` = 회차 날 자정 − `promotion_cutoff_hours` 이후)에는 홍보 권고 문구에 "시작 시각이 없어 홍보 중단이 지났는지 확인하지 못함"을 붙이고 근거에 `earliest_cutoff_ts/<회차>` · `now` · `policy/<회차>/promotion_cutoff_hours`를 넣는다. 시작 시각은 YAML에서 따옴표로 감싼다. 따옴표가 없으면 YAML 1.1이 `19:30`을 정수 1170으로 읽어 00:19:30이 되므로 모델이 거부한다.

**잠정 마감 권고 (`cap`, #51)**: 비율 목표가 있는 회차에서 한쪽 확정이 상대보다 `max_diff`를 넘게 많으면, 앞선 쪽을 "상대 확정 + `max_diff`"에서 잠정 마감하라고 권고한다(`Decision.kind = cap`, `need` = 상한). 운영사가 신청폼에서 한 성별을 닫고 다른 성별이 늘면 다시 여는 일을 손으로 하던 것(운영 자료 T0316 · T0375)이다. 홍보 권고와 같이 엔진은 권고만 하고 폼을 닫는 것은 사람이 한다. 회차가 찼거나 지났으면 내지 않는다. 입금 대기는 세지 않는다(불균형과 같은 기준). 규칙은 양방향(대칭)이며 `max_diff`를 행에 함께 싣는다. **잠정 마감된 값은 홍보 권고를 내지 않는다**(`!capped`): "여성 3명 부족, 홍보"와 "여성 잠정 마감"이 같이 나오면 모순이라서, 앞선 쪽은 상대가 따라올 때까지 기다린다. 기본 한도 없이 차가 `max_diff`를 넘는 즉시 권고하는 것은 **가정**이다(운영사 확인 중).

## 8. 보안 · 데이터

- 저장소에는 **합성 데이터만** 둔다 (`data/synthetic/`). 실제 데이터는 `data/private/`(gitignore)에만 두고 LLM에 보내지 않는다.
- 모델에 개인 식별 칸이 없다 (3절). 시나리오 파일의 id는 `r1`, `s1` 같은 합성 id다.
- 운영사 이름 · 고객 코드 · 내부 문서는 저장소 어디에도 적지 않는다. 정책 파일의 예시 모임 이름도 합성이다.
- 비밀값은 환경변수로만. `.env.example`에는 이름만 (공용 보안 기준).
- 엔진 출력 · 로그에는 참가자 id와 집계 숫자만 나온다.

## 9. wirelog 0.70.0 제약과 우회 (2026-10-29 Intel Mac 검증)

| 제약 (사실) | 우회 |
|---|---|
| 본문에서 `G = Lo - F` 같은 변수 바인딩은 오류 없이 **빈 결과**를 낸다 | 산술은 head에 쓴다: `gap(S, D, V, Lo - F) :- ..., Lo - F > 0.` 필요하면 중간 관계로 나눈다 |
| 산술의 괄호 `X - (Y - X)`는 파싱 오류다. `/`(정수 나눗셈, 버림)는 되고 `-` · `+`보다 먼저 계산된다 | 괄호가 필요한 식은 중간 관계로 나눈다(`window_slack`, #91 C) |
| `min` `max` `count` `sum`은 열 이름으로 못 쓴다 (파싱 오류) | 목표 열은 `lo` · `hi` |
| PyreWire는 Python에서 intern하지 않은 symbol을 되돌리지 못한다 (`.dl` 안의 상수 · head 상수는 정수 id로 나옴) | `engine.py`가 규칙 파일의 따옴표 상수를 미리 `intern`하고, 데이터 사실은 모두 Python에서 `insert`한다 |
| `EasySession.snapshot`은 입력 관계(EDB)에 빈 결과를 돌려준다 | `engine.py`가 넣은 사실을 함께 보관하고 입력 관계는 거기서 읽는다 |
| `BatchProgram`은 inline 사실을 자동 적재하므로 `load_all_facts()`를 또 부르면 두 배로 센다. 결과 symbol도 id로만 나온다 | `EasySession`만 쓴다. `.dl`에 데이터 사실을 쓰지 않는다 |

검증 스크립트: `scripts/verify_wirelog.py` (28건 중 27건 통과, 실패 1건은 위 첫 줄의 기록용). 3c는 `min` · `max` 집계와 head 산술, 사실을 지운 뒤 다시 계산되는지 확인한다(#91). 3d는 head 나눗셈과 우선순위, 11d는 괄호가 거부되는 것을 확인한다(#91 C).

## 10. 저장소 구조

```
rules/            ontology.dl  capacity.dl  promotion.dl  triage.dl   (패키지에는 event_ops_engine.rules로 들어간다, #70)
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
docs/             design.md glossary.md decisions/
```

## 11. 테스트 전략

- 계산 로직은 같은 PR에 단위 테스트를 올린다 (공용 테스트 기준 1번).
- lib 모듈은 순수 함수 테스트. 규칙은 시나리오 5개(1인 · 2인 혼성 · 단체 · 1:1 비율 · 경계)를 엔진에 넣고 파생 관계와 `Decision`을 확인한다.
- 취소는 (a) 상태 이력 (b) 사실 철회 두 경로를 모두 테스트한다.
- 엔진 라이브러리: `WIRELOG_LIB`가 비어 있고 `vendor/wirelog/build/libwirelog.1.dylib`가 있으면 `tests/conftest.py`가 자동으로 잡는다. 둘 다 없으면 wheel에 든 엔진을 쓴다(Linux CI).
- 설치 확인 (`make wheel-smoke`, #80): wheel을 새 venv에 설치하고 저장소 밖 임시 폴더에서 `report` · `triage`를 실행한다. 불러온 패키지가 그 venv 안의 것인지도 확인한다. CI(ubuntu)가 매번 돌리고, Intel Mac에서는 `WIRELOG_LIB`를 주고 돌린다.

**성능 측정 (#34)**: `make bench`(`scripts/bench.py`)가 `synthetic.py`의 seed 고정 합성 신청으로 `report` 단계와 문의 판정 시간을 잰다. 신청 구성은 1인 60% · 혼성 2인 25% · 같은 성별 2인 10% · 구성 미상 5%이고, 최종 상태는 확정 60% · 입금 대기 15% · 취소 15% · 신청 10%다. 생성기 결과를 Python으로 직접 센 값과 규칙의 집계가 같은지는 `tests/test_synthetic.py`가 확인한다. 측정은 CI에서 돌리지 않는다(몇 분 걸리고 시간 값이 기계마다 다르다).

2026-11-07, Intel Mac (x86_64) · Python 3.11, 3회 중앙값. 단계별 값은 조회 캐시(#83) 뒤, 마지막 열은 캐시 전(#82) 합계:

| 회차 × 신청 | 신청 | 참가자 | 사실 행 | 사실 만들기 | 엔진 적재 | 현황 | 홍보 | 합계 | 캐시 전 합계 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 5 × 20 | 100 | 135 | 818 | 0.001s | 0.007s | 0.007s | 0.001s | 0.017s | 0.056s |
| 15 × 20 | 300 | 424 | 2,546 | 0.004s | 0.017s | 0.020s | 0.005s | 0.045s | 0.497s |
| 50 × 20 | 1,000 | 1,406 | 8,405 | 0.013s | 0.047s | 0.093s | 0.042s | 0.194s | 5.642s |
| 150 × 20 | 3,000 | 4,211 | 25,204 | 0.052s | 0.155s | 0.542s | 0.328s | 1.078s | 53.218s |
| 1 × 300 | 300 | 424 | 2,406 | 0.003s | 0.014s | 0.023s | 0.001s | 0.042s | 0.068s |
| 1 × 1,000 | 1,000 | 1,406 | 7,915 | 0.012s | 0.044s | 0.186s | 0.003s | 0.247s | 0.311s |

문의 판정(문의 1건, 같은 회차 신청 100 · 300 · 1,000건): 0.027s · 0.074s · 0.331s (캐시 전 0.027s · 0.064s · 0.312s). 같은 기계에서도 실행마다 10~15% 차이가 났다.

- 캐시 전에는 **회차 수에 따라 거의 제곱으로** 늘었다. `Engine.rows()`가 부를 때마다 관계 전체를 엔진에서 다시 받아(`snapshot`) Python에서 회차로 걸렀기 때문이다. 50회차에서 현황 한 번에 엔진 `snapshot` 호출이 700번이었다(cProfile). 엔진 평가가 아니라 반복 조회가 비용이었다.
- **조회 캐시 (#83)**: `Engine`이 관계별 정렬 결과와 앞 열(회차 등)별 색인을 저장해 두고, `insert` · `remove` 때 모두 비운다. 엔진 조회는 관계마다 한 번이 되어 150회차 × 20건이 53초에서 1.1초로 줄었다. 돌려주는 목록은 복사본이다.
- 한 회차의 신청 수에는 거의 비례한다(1,000건 0.25초). 문의 판정은 질문마다 사실을 넣고 빼므로 캐시 효과가 거의 없다.
- 실제 회차 설정 32개(정원 20명이 가장 많음)는 15~50회차 사이라, 전체 `report`가 0.2초 안으로 예상된다(추정, 실제 데이터로 재지 않음).

## 12. 확인하지 못한 것

- Linux에서의 속도 — `make bench`는 Intel Mac에서만 쟀다 (11절).
- `average` 등 다른 집계 함수 — 규칙은 `count` · `max` · `min`만 쓴다(`min`은 #91에서 검증 3c로 확인).
- 실제 운영사 정책값 — 7절 기준값 중 `promotion_cutoff_hours`만 확인됨이고 나머지는 가정값이다 (#52).

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
| 2 외부 요인 (#16) | `delivery` | `message_sent{result: timeout}` · 그 뒤의 전달 증거 `provider_receipt{result: delivered}` 또는 `provider_lookup{result: found}`. 둘 사이에 **수동** 재발송이 있으면 애매(`resent_between`); 예정된 자동 재발송 `message_sent{auto: true}`은 세지 않는다(#49). 증거에 `of: <발송 id>`가 있으면 그 발송만 증명(#49) | `external_delay` (실제 전달됨, 재발송 불필요) | 발송 · 증거 id | 그 발송에 대한 수신증도 조회도 없으면 `provider_lookup` |
| 2b 외부 연결 실패 (#47) | `delivery` | `message_sent{result: timeout}` · 그 뒤의 `provider_lookup{result: none}`, 전달 증거 없음 | `external_failure` (업체에 닿지 못함, 재발송) | 발송 · 조회 id | 같음 |
| 3 정책상 정상 (#18) | `duplicate` | `registration_submitted{participant}` (질문 대상과 같은 회차의 다른 신청) | 같은 회차에 같은 참가자 키가 둘이면 `policy_normal` | 두 제출 이벤트 id | 질문 대상에 제출 기록이 없으면 `registration_submitted` |
| 4 기한 만료 (#19) | `deadline` | `payment_attempt{result: rejected}` · 기한은 `due_time`: 최신 `payment_due` 로그, 없으면 입금 대기 시작 + `payment_deadline_hours`(회차 override 가능) | 거절된 시도 시각 > 기한 + `grace_minutes`이면 `expired` (은행이 받아 준 시도는 제외) | 시도 id + 기한 로그 id 또는 `rule/due_time` | 기한을 알 수 없으면 `payment_due`, 시도가 없으면 `payment_attempt` |
| 5 버그 의심 (#20) | 주제 무관 (`in_scope`이면) | 불변식 세 개: 확정인데 `payment_received`가 없고 **확정 뒤 입금 조회 `payment_lookup{result: none}`도 없음**(#58) · `payment_received`가 최신 기한 + `grace_minutes` 뒤 · 확정 참가자의 속성 값이 ② `over_capacity` | `suspected_bug` | `rule/<불변식 이름>` (+ 조회 로그 id) | 확정 · 입금 기록 없음 · 조회 없음이면 `payment_lookup` (주제와 관계없이. 최신 조회만 본다) |
| 7 입금 반영 지연 (#50) | `payment` | 상태 입금 대기 · `payment_received` 없음 · 최신 `payment_lookup{result: found}` | 조회 시각이 `now` − `sync_lag_minutes` 안이면 `sync_lag`(반영 대기, 기다린다), 넘으면 불변식 `paid_but_pending` → `suspected_bug` | 조회 id (+ `rule/paid_but_pending`) | 입금 대기인데 조회가 없으면 `payment_lookup`. 최신 조회가 `none`이면(업체에도 입금 없음) 원인도 `needs`도 없어 `ask`: "입금 안 됨"을 말하는 유형은 아직 없다 |
| 6 자리 문의 (#21) | `seat` | 후보 사실 `about_session` · `about_value` + ② `full` · `over_capacity` | 마감(확정 + 입금 대기가 상한에 닿음)이면 `seat_full`, 확정이 상한을 넘으면 `over_capacity` (하나만) | `rule/full` · `rule/over_capacity` + 후보 사실 id | 회차 · 속성 값이 없으면 `session` · `attribute_value`, 그 값에 목표가 없으면 `target` |

**자료와 일치** (#44 · #78, 가명화 운영 대화와 대조):

- 유형 1: 안내된 계좌는 14자리인데 신청자가 13자리를 입력한 사례 (T0566~T0567). 합성 시나리오 `account-length.yaml`도 같은 구조(발급 14 · 입력 13)다.
- 유형 3: 같은 모임 + 회차 + 이름 + 번호의 신청이 둘이면 막지 않고 중복으로 표시만 한다 (T0534~T0537). 엔진의 참가자 키가 실제 시스템의 "이름 + 번호"에 해당한다 (glossary "참가자 키").
- 유형 4: 기한이 지난 뒤의 입금 시도는 거절된다 (T0304~T0305 · T0549~T0550. T0548은 외부 요인과 함께 라벨되어 빼냄). 유예 0은 아래 `grace_minutes`의 근거와 같다.

`triage_policy(key, n)`은 유형 규칙의 정책값(`policy/events/*.yaml`의 `triage:`): `grace_minutes`(기본 0, 은행이 기한 시각에 바로 막는다는 운영 자료 T0549에 따름)와 `payment_deadline_hours`(기본 24, 선별 뒤 N시간, 회차별 `payment_deadline_hours`로 덮어씀, 운영 자료 T0577 · 회차 설정 32개). 이 둘은 가정값이 아니라 **자료로 확인한 값**이다. `sync_lag_minutes`(기본 10, 유형 7)는 **가정값**이다(실제 시스템의 입금 확인 주기가 10분에서 실시간으로 바뀜, T0287~T0305). 참가자 키(`participant`)는 합성 식별자이며 실명 · 연락처를 두지 않는다. 유형 5의 `over_capacity` 근거는 불변식 이름뿐이라 어느 속성 값이 초과인지는 `event-ops report`로 본다(규칙 안에서 문자열을 만들 수 없어서, 9절). 유형 5는 입금 기록이 **없다는 것만으로** 버그를 확정하지 않는다(아래 "기록 없음 ≠ 없음"). 같은 질문에 유형 5와 다른 유형이 함께 걸리면 원인이 둘이라 `ask`가 되고, 이것은 의도한 동작이다. `needs` 값에는 확인 주체가 붙어 나온다(`harness.NEEDS_VERIFIER`: 외부 = 발송 업체 로그, 내부 = 관리자 기록, 질문 = 묻는 사람, 정책). 관리자 알림의 '실패'는 보수적인 메모이고 전달 여부의 진실은 업체 로그라서다(운영 자료 T0551 · T0583). 원인이 하나라도 파생되면 `needs`는 비운다 (다른 이벤트의 '아직 없는 사실'이 확정된 원인에 끌려 나오지 않게). 자릿수가 같거나 수신증이 `failed`이면 원인도 `needs`도 없어 `ask`가 된다. 그 경우는 아직 유형이 없다는 뜻이고, #18~#21에서 유형이 늘면 거기서 판정된다. 시나리오 파일은 `expected`(기대 판정 · 원인 · needs)를 적고, `event-ops triage`는 실제 판정과 비교해 다르면 종료 코드 1을 낸다. `cause` · `needs`를 비우면(null) 비교하지 않고, `needs: []`는 '더 필요한 사실 없음'을 단언한다.

**기록 없음 ≠ 없음 (열린 세계, #58)**: Datalog의 부정(`!`)은 "넣은 사실에 없다"는 뜻이다(닫힌 세계). 로그 연동이 덜 되면 "없다"가 틀린 결론이 된다. 그래서 부정을 쓰는 곳을 세 가지로 나누고, **원인을 확정하는 데에는 "조회했는데 없었다"는 사실만 쓴다.**

| 쓰임 | 규칙 | 전제 |
|---|---|---|
| 더 필요한 사실을 묻는다 | 모든 `needs` 규칙 | 없음 → 확인 요청. 열린 세계와 맞음 |
| 집계 · 기본값 | ② `filled` 0, `due_time`(기한 로그가 없으면 정책 시간), `superseded` | 넣은 신청 · 상태 이력이 그 회차의 전부라는 전제. 연동 시 회차 단위로 빠짐없이 넣어야 함 |
| 원인을 확정한다 | 유형 2b `provider_lookup{none}`, 유형 5 `payment_lookup{none}` | 사람이 업체 기록을 **조회한 결과**가 있어야 함. 조회 전에는 `needs` |
| 원인을 막는다 | 유형 2 `resent_between`, 유형 2b `proof_after`, 유형 6 `!over_capacity` | 재발송 · 증거 로그가 빠지면 원인이 잘못 나올 수 있음. 남은 위험 |

**확신도 기준 (#59)**: 해석기가 낸 후보 사실 중 `confidence`가 `triage.min_candidate_confidence`(가정값 0.6)보다 낮은 것은 규칙에 넣지 않는다. 검증(없는 id · 관계 · 인용 → `reject`)은 확신도와 관계없이 먼저 한다. 제외한 후보는 `Verdict.dropped`(후보 id), 판정 메시지, trace에 남는다. 같은 사실이 여러 번 제안되면 하나라도 기준을 넘으면 쓴다.

**근거 등급 (#60)**: `event-ops triage`는 근거를 믿을 수 있는 순서로 줄을 나눠 보인다. ① 명시 사실(asserted) `log/…`(기록된 로그) ② 추론 사실(inferred) `rule/…`(규칙이 기록에서 파생한 사실) ③ LLM 추출 후보(검증 통과) `candidate/…`(해석기가 질문에서 뽑아 관계 · id · 인용 검증을 통과한 사실) ④ 질문 `question/…`. "확인 불가"는 등급이 아니라 판정 자체(`ask` 확인 요청 · `abstain` 판정 보류)로 나타난다. 이름은 OWL 도구에서 쓰는 asserted / inferred 구분을 따른다.

**실제 해석기 확인 (#61)**: `--interpreter claude` · `--normalizer claude`면 시작 전에 `claude -p`로 한 번 응답을 확인한다(설치됨 ≠ 로그인됨). 안 되면 판정을 하지 않고 종료 코드 2. 로그인 확인은 짧은 실제 호출 1회다. `--runs N`은 같은 질문을 N번 판정해 (판정 · 원인) 분포와 일치율을 내고, 기대 판정이 있으면 모든 실행이 맞아야 종료 코드 0이다. 정규화는 반복 밖에서 한 번만 하므로 해석기의 변동만 재고, `--trace`는 첫 실행만 보인다.

**해석기**: 기본은 Claude Code CLI(`claude -p`, 구독 안 · 추가 비용 0), 테스트는 가짜 해석기(시나리오 파일의 `canned` 응답). API는 쓰지 않는다. LLM 출력은 JSON이며 `Interpretation` 모델 검증을 통과해야 한다. 실제 CLI는 관계 서명의 `q`를 `args`에 같이 넣는 경우가 있어(2026-11-04 확인, #61) 하네스가 검증 전에 앞의 질문 id를 떼어 낸다. 다른 id는 떼지 않는다.

## 14. 속성 정규화 (`job_group`, `normalizer.py`, `capacity.dl`)

자유 입력(예: "백엔드 3년차")을 정책의 범주 값 중 하나로 바꾼다. ①과 같은 원칙이다: **LLM은 제안만, 규칙이 받아들인다.**

| 단계 | 하는 일 | 코드 |
|---|---|---|
| 정책 | `dimensions.job_group: { values: [...], normalize: llm, min_confidence: 0.7, aliases: {값: [단어…]} }` (기준값은 가정값, 별칭 사전은 사람이 PR로 승인) | `model.py` `JobGroupDimension` |
| 별칭 사전 (#62) | 문구에 **한 값**의 별칭만 보이면 LLM 없이 확정(확신도 1.0, 인용 = 문구에 쓰인 그대로). 값 이름 자체는 별칭이 아니다(사람이 적은 단어만). 영문 별칭은 단어 단위로만 맞춘다("UX"가 "luxury"에 걸리지 않게). 같은 단어를 두 값에 적으면 정책 로드에서 거부. 걸리는 값이 없거나 여럿이면("마케팅 겸 기획") 정규화기로 | `normalizer.match_alias` |
| 정규화 | 남은 문구마다 정규화기가 `NormalizedValue(value, confidence, quote)`를 제안. **같은 문구는 한 번만**, Claude CLI 정규화기는 남은 문구를 **한 프롬프트**(최대 40개씩)로 묻는다(#63, 호출 1회 ≈ 1분). `quote`가 문구에 없거나 답이 없으면 `unknown` · 확신도 0 | `normalizer.resolve_texts` · `normalize_members` (Claude Code CLI · 가짜) |
| 사실 | 후보는 `candidate_attr(attendee, job_group, value, 확신도%, job/<attendee>)`, 문구가 없으면 `given_attr(…, job_group, unknown)`. 확신도는 1% 해상도로 **내림**(0.695는 0.7 기준을 넘지 못한다) | `facts.py` |
| 규칙 | 확신도 ≥ 기준이고 값이 허용 목록에 있으면 `attendee_attr`로 올린다. 기준 미만이면 `unknown` + `needs_review(…, "low_confidence")`, 목록 밖 값이면 `unknown` + `needs_review(…, "unknown_value")`. 네 규칙은 서로 배타적이라 참가자마다 값이 하나다(wirelog는 중복을 남기므로 `count`가 두 번 셀 수 있다) | `capacity.dl` |
| 결과 | ② 현황이 `job_group` 목표를 보통 속성처럼 계산하고, 확인 요청에 근거 `job/<attendee>`가 붙는다 | `capacity.py` |

`attendee_attr`는 이제 파생 관계다(wirelog는 한 관계에 입력과 규칙을 섞지 못한다, 9절). 입력은 `given_attr`로 들어온다. `event-ops report --normalizer claude`(triage도 같은 옵션)가 실제 CLI를 쓰고, 기본 `fake`는 시나리오의 `canned_job_groups`를 쓴다. `job` 문구는 합성이며 이름 · 연락처를 두지 않는다(8절). 문의 판정의 주제에도 같은 방식의 사전(`triage.topic_aliases`, 예: delivery ← 문자 · 카톡 · 알림톡)이 있고, 해석기 프롬프트에 그대로 들어간다. 주제는 질문 전체를 읽어야 해서 사전만으로 확정하지는 않는다.

## 15. 온톨로지 용어로 본 설계

온톨로지 · 뉴로-심볼릭 에이전트 분야의 용어로 이 설계를 다시 적는다. 새 기능이 아니라 같은 구조를 다른 이름으로 본 것이다.

| 용어 | 뜻 | 이 설계에서 |
|---|---|---|
| T박스 (용어 · 정의) | 종류 전체에 대한 정의 | `rules/ontology.dl`의 관계 선언(사실 스키마), 정책 파일의 속성 · 값 정의와 별칭 사전. `rules/*.dl`의 규칙은 이 위에서 도는 추론 규칙이다 |
| A박스 (개별 사실) | 특정 대상에 대한 주장 | 시나리오에서 만든 사실 (`registration` · `status_event` · `log_event` · 회차별 목표 · 후보 사실 …). T박스 · A박스는 역할을 나누는 말이고 파일을 나누라는 뜻은 아니다 |
| 추론 · 고정점 | 더 나올 결론이 없을 때까지 규칙을 적용 | wirelog가 ② · ③ · ① 관계를 파생. 재귀 규칙은 아직 쓸 곳이 없어 두지 않음 |
| 명시 vs 추론 (asserted vs inferred) | 원본은 바뀌지 않고, 추론 결과는 따로 본다 | 근거 등급: `log/` 명시 사실, `rule/` 추론 사실, `candidate/` LLM 추출 후보(검증 통과) (13절) |
| 도메인 · 레인지 | 관계의 앞 · 뒤에 올 수 있는 종류 | 후보 사실의 인자 종류 검사(신청 · 회차 · 로그 id · 속성 값). OWL처럼 모르는 이름을 새 개체로 **추론하지 않고 거부**한다(SHACL식 검증) |
| 일관성 (모순) | 설명들이 동시에 참일 수 있는가 | 불변식 위반(유형 5) → `suspected_bug`. 추론은 충돌을 알려 줄 뿐, 어느 쪽이 틀렸는지는 사람이 판단 |
| 열린 · 닫힌 세계 | 기록이 없는 것이 거짓인가 | Datalog 부정은 닫힌 세계. 판단에는 "기록 없음"이 아니라 "조회했는데 없음"만 쓰고, 그것도 "그곳에서 찾지 못함"일 뿐이라 결제 기록 없는 확정은 버그 **의심**(사람 확인)으로 넘긴다 (13절 표) |
| 이름 둘 ≠ 대상 둘 | 다른 이름이 같은 대상일 수 있다 | 별칭 사전(14절). 유형 3은 다른 참가자 키를 "다른 사람"으로 단정하지 않는다(원인 없음 → `ask`) |
| 승인된 사전으로 추출 | 사전을 먼저 만들고 사람이 승인한 뒤 그걸로 추출 | 닫힌 어휘(후보 관계 5개 · 주제 5개 · 속성 값)와 별칭 사전. 승인은 PR 리뷰 |
| 작은 입력 + 기대 결과 | 추론기 지원 범위를 작은 예제로 먼저 확인 | 시나리오의 `expected`, README 출력 대조 테스트, `scripts/verify_wirelog.py` |

**검토했지만 반영하지 않은 것과 이유**

- RDF · OWL · Jena · SPARQL · Fuseki: 자바 스택이고, 이 규모에서는 Datalog 관계 + 규칙으로 충분하다.
- 재귀 규칙(도달 가능성 같은 고정점 계산): 지금 문제에 쓸 곳이 없다. 보여 주기용으로 넣지 않는다.
- 에이전트 오케스트레이션 · 병렬 실행 · 상주 CLI 프로세스 · OpenRouter API: 복잡도가 크고, 유료 API는 승인이 필요하다. 호출 수는 별칭 사전과 묶음 프롬프트로 줄였다.
- 열린 이슈를 골라 구현 · 머지까지 자동으로 하는 에이전트 스킬: CI가 통과하면 자동 머지한다. 사람이 머지하는 원칙과 맞지 않는다.
- wirelog 0.80(11월 예정): 나오면 `scripts/verify_wirelog.py`로 문법 · 동작을 다시 확인한다(백로그).

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
| 2026-11-02 | 운영 자료 반영: 입금 대기를 자리로 셈(6절), 기한 = 선별 후 N시간 · 유예 0 (13절 유형 4) (#45 · #46) |
| 2026-11-07 | 7절 홍보 중단(`promotion_cutoff_hours`, 확인됨) · 회차 시작 시각 · 회차별 덮어쓰기, 기준값 확인됨/가정 표시. 3 · 5 · 12절 (#52) |
| 2026-11-07 | 4 · 13절 운영 자료와 일치한 항목 표시: 인원 환산, 유형 1 · 3 · 4 (#78) |
| 2026-11-07 | 11절 설치 확인 `make wheel-smoke`: Linux CI에서 설치한 wheel을 저장소 밖에서 실행 (#80) |
| 2026-11-07 | 11절 성능 측정 `make bench`와 결과, 12절 속도 항목 갱신 (#34) |
| 2026-11-07 | 11절 조회 캐시(#83)와 다시 잰 값 |
| 2026-11-07 | 2절 결과 JSON 출력 `--json` (`event-ops/report@1` · `event-ops/triage@1`, #85) |
| 2026-11-08 | 3절 선택 속성 `dimensions.choices` · `attrs`, 선언하지 않은 목표 거부 (#31) |
| 2026-11-08 | 3 · 4절 2인 신청 유형 `pair` (#33) |
| 2026-11-09 | 3 · 4 · 5 · 6절 조합 목표(성별 + 나이 범위)와 운영사 확인 사실, 출생연도 없음 확인 요청, 2절 JSON 번호 규칙(필드 추가는 같은 번호) (#32) |
| 2026-11-09 | 7절 조합 권고: 성별 결정에 묶기(`Decision.parts`), 필요 인원, 잠정 마감이면 조용히, 남은 자리보다 크면 `gender_room` 보류 (#32) |
| 2026-11-10 | 3 · 5 · 6절 비슷한 나잇대(#91 A): 정책 `similar_age`, 성별 · 묶음(확정·대기 / 신청 접수)별 나이 목록과 폭, 출생연도 없음 수, 2절 JSON `ages`. 9 · 12절 `min` 집계 검증 |
| 2026-11-10 | 3 · 5 · 6절 폭 확인 요청(#91 B): `similar_age.max_spread`(회차 덮어쓰기), 회차 × 성별 `age_spread_review`, 확인 요청 줄 |
| 2026-11-10 | 2 · 3 · 6 · 9절 범위 제안(#91 C): 가운데 맞춤 · 동점 후보 모두 · 조합 있는 성별 제외, JSON `range_suggestions`, wirelog 나눗셈 · 괄호 제약 |
