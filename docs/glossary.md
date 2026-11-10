# 용어집

기준: 공용 용어 기준([CONTRIBUTING.md](../CONTRIBUTING.md)). 한 개념 = 한 이름. 코드 · 규칙 파일 · 문서 · 테스트가 모두 이 표를 따른다.
용어를 바꾸면 문구 · 코드 · 규칙 · 문서를 **같은 PR에서** 함께 바꾼다.

## 용어

| 개념 | 사용자 문구 (한국어 / 영어) | 코드 · 규칙 · 문서 | 쓰지 않는 말 | 메모 |
|---|---|---|---|---|
| 하나의 모임 상품. 여러 회차를 가진다 | 모임 / event | `event` | 개더링, 프로그램, 밋업(부제 제외) | 운영사 문서의 "프로그램"은 상품을 뜻하므로 여기서는 쓰지 않는다 |
| 모임의 한 번 열림 (날짜 · 장소 · 정원이 있는 단위) | 회차 / session | `session` | 차수, 오프라인 모임 | 판단은 모두 회차 단위로 한다 |
| 한 건의 신청 (1인 · 2인 · 단체 모두 한 건) | 신청 / registration | `registration` | 지원, 예약 | 정원은 신청 건수가 아니라 **사람 수**로 센다 |
| 2인 신청이 신청폼에서 고른 성별 구성 | 2인 신청 유형 / pair type | `pair`: `female_pair`(여여) · `male_pair`(남남) · `mixed_pair`(혼성) | 커플, 짝 | 유형만 있으면 성별이 정해진 참가자 2명으로 펼치고 출생 연도는 모른다. 나이를 읽는 모임에서는 확인 요청이 된다 ([design.md 4](design.md#4-인원-환산)) |
| 신청을 낸 사람 | 신청자 / registrant | `registrant` | 지원자 | 동반자 정보를 함께 적는 사람 |
| 회차에 자리를 차지하는 한 사람 (신청자 또는 동반자) | 참가자 / attendee | `attendee` | 멤버, 회원 | 신청 1건 → 참가자 n명으로 펼친다 ([design.md 4](design.md#4-인원-환산)) |
| 같은 사람의 신청인지 가리는 값 | 참가자 키 / participant key | `registration_submitted{participant}` (① 유형 3) | 회원 id, 고객 번호 | 실제 시스템에서는 모임 + 회차 안의 이름 + 번호. 저장소와 엔진에는 **합성 식별자만** 둔다. 같은 키가 둘이면 막지 않고 표시만 한다(운영 자료와 일치, [design.md 13](design.md#13-운영-문의-판정-①-rulestriagedl-harnesspy)) |
| 참가자의 한 가지 속성 (성별 · 나이 구간 · 직군 · 신청 방식) | 속성 / attribute | `dim` (속성 이름), `value` (속성 값) | 카테고리, 태그 | `attendee_attr(attendee, dim, value)` |
| 신청폼에서 정해진 목록 중 고른 속성 (지역 · 참여 방식) | 선택 속성 / choice attribute | 정책 `dimensions.choices`, 신청 · 참가자 `attrs` | 카테고리, 태그, 옵션 | 값 목록과 단위(`per: member` · `registration`)를 정책에 선언한다. 정규화하지 않는다. 목록 밖 값은 입력 오류 ([design.md 3](design.md#3-데이터-모델-python-modelpy)) |
| 성별 하나와 나이 범위를 묶은 모집 단위 (예: 여성 25~29세) | 조합 / combination | 정책 `combos`(회차 덮어쓰기), 목표 `targets.combo.<id>`, 속성 이름 `combo` | 교차 속성, 세그먼트 | 나이 범위는 양 끝 포함, 연 나이. 같은 성별 조합끼리 범위가 겹치면 입력 오류 ([design.md 3](design.md#3-데이터-모델-python-modelpy)) |
| 한 회차 사람들의 나이가 서로 가까운 상태. 범위는 담당자가 신청 현황을 보고 정한다(보통 10~15살 차이 이내, 운영사 확인) | 비슷한 나잇대 / similar age | 정책 `similar_age`, `similar_age(session)` | 연령 제한, 나이 필터 | 엔진은 범위를 정하거나 사람을 거르지 않고, 성별마다 나이를 보여 준다 ([design.md 3](design.md#3-데이터-모델-python-modelpy)) |
| 한 성별 · 묶음 안에서 가장 많은 나이 − 가장 적은 나이 (연 나이) | 나이 폭 / age spread | `age_spread(session, gender, pool, years)` | 나이 차, 연령 범위 | 폭은 성별마다 잰다(사용자 결정 2026-11-09). 기준 `similar_age.max_spread`(가정값)보다 확정·대기 폭이 크면 확인 요청, 같으면 괜찮음 (#91 B) |
| 조합이 아직 없는 성별에서, 폭 기준만큼의 나이 범위 중 확정·대기가 가장 많이 드는 것 | 나이 범위 제안 / range suggestion | `range_suggestion(session, gender, low, high, covered)` | 추천 연령, 타깃 연령 | 든 사람들을 가운데에 둔다. 동점이면 후보를 모두 보인다. 담당자가 골라 조합으로 적는다 (#91 C) |
| 나이를 모으는 두 묶음: 자리를 차지한 사람(확정 · 입금 대기)과 아직 고르지 않은 사람(신청 접수) | 확정·대기 / 신청 접수 (age pool) | `age_pool(reg, pool)`, `occupying` · `applied` | 참가자 / 대기자 | 출력은 나이와 수만 쓴다. 신청 id는 붙이지 않는다 |
| 회차 · 속성 값마다 정한 인원 하한 · 상한 | 목표 / target | `target(session, dim, value, lo, hi)` | 쿼터, 할당 | wirelog 예약어 때문에 열 이름은 `min` · `max`가 아니라 `lo` · `hi` |
| 같은 속성의 두 값 사이 허용 차이 (예: 성별 1:1) | 비율 목표 / ratio target | `ratio_target(session, dim, value_a, value_b, max_diff)` | 균형 조건 | `max_diff`는 허용하는 인원 차 |
| 확정된 참가자가 차지한 자리 수 | 차지한 자리 / filled | `filled` | 현재 인원, 모집 인원 | 입금 대기는 포함하지 않는다 |
| 목표 하한까지 더 필요한 사람 수 | 부족분 / gap | `gap` | 미달, 결원 | `lo - filled - pending`, 0보다 클 때만. 입금 대기도 자리를 차지한 것으로 본다 |
| 목표 상한까지 더 받을 수 있는 사람 수 | 남은 목표 자리 / remaining | `remaining` | — | `hi - filled - pending` (음수면 초과) |
| 회차 정원에서 남은 사람 수 | 남은 자리 / remaining seats | `remaining_seats` | 잔여석 | `session_capacity - session_filled - session_pending` (운영사 규칙) |
| 신청했으나 아직 입금하지 않은 상태 | 입금 대기 / pending payment | `pending_payment` | 미입금, 대기 | 자리를 차지하지 않는다. 현황에는 따로 보여 준다 |
| 입금이 확인되어 자리가 확정된 상태 | 확정 / confirmed | `confirmed` | 승인, 완료 | `filled`에 세는 유일한 상태 |
| 신청자가 취소하거나 운영사가 취소 처리한 상태 | 취소 / cancelled | `cancelled` | 철회, 반려 | 자리를 돌려준다. 규칙에서는 "최신 상태가 cancelled" 또는 사실 철회(remove)로 표현 |
| 환불까지 끝난 취소 | 환불 / refunded | `refunded` | — | 자리 계산은 `cancelled`와 같다 |
| 신청 상태가 바뀐 사건 (시각 포함) | 상태 이력 / status event | `status_event(registration, ts, status)` | 로그 | 가장 최근 시각의 상태가 현재 상태 |
| 속성 값이 아직 확인되지 않음 | 미상 / unknown | `"unknown"` (예약 값) | 기타, 없음 | 신청 방식 칸이 없던 옛 신청. 목표 집계에서 빼고 검토 대상으로 올린다 |
| 홍보를 권하는 판단 | 홍보 권고 / promotion recommendation | `promote(session, dim, value, need, reason)` | 홍보 지시, 자동 홍보 | 엔진은 권고만 하고 실행은 사람이 한다 |
| 비율에서 앞선 쪽을 상대가 따라올 때까지 막아 두라는 판단 | 잠정 마감 권고 / cap | `cap(session, dim, value, limit, other, other_filled, max_diff)` · `Decision.kind = cap` | 자동 마감 | 상한 = 상대 확정 + `max_diff`. 잠정 마감된 값은 홍보 권고를 받지 않는다. 폼을 닫는 것은 사람이 한다 |
| 부족분이 있지만 홍보할 수 없는 상태 (예: 정원 마감) | 홍보 보류 / blocked | `blocked(session, dim, value, need, reason)` | — | 목표와 정원이 충돌한 것을 운영자에게 보인다 |
| 회차 시작까지 남은 날 수 | 남은 날 / days left | `days_left(session, days)` | D-day | 기준 시각(`now`)에서 Python이 계산해 사실로 넣는다 |
| 홍보 판단에 쓰는 설정값 | 홍보 기준 / promotion policy | `policy(session, key, n)` | 임계값 | `lead_days`, `trend_min_per_week`, `promotion_cutoff_hours`. `promotion_cutoff_hours`만 **확인됨**, 나머지는 **가정값** ([design.md 7](design.md#7-홍보-판단-③)). `lead_days` · `promotion_cutoff_hours`는 회차마다 덮어쓸 수 있다 |
| 이 시각부터 홍보 권고를 내지 않음 | 홍보 중단 / promotion cutoff | `promotion_cutoff_ts(session, ts)` · `past_cutoff(session)` | 홍보 마감 (정원 마감 · 잠정 마감과 헷갈림) | 시작 시각 − `promotion_cutoff_hours`. `promote`만 멈추고 `blocked` · `cap`은 그대로 |
| 판단 결과 하나 (권고 · 보류 · 확인 요청) | 판단 / decision | `Decision` (Python) | 알림 | 근거 사실 id 목록을 반드시 같이 가진다 |
| 판단을 떠받치는 입력 사실 | 근거 / evidence | `evidence` (fact id 목록) | — | 예: `target/s1/gender/female`, `registration/r3` |
| 담당자가 올린 운영 문의 한 건 | 문의 / question | `question(q)` | 티켓, 이슈 | 합성 질문만 둔다. 자유 서술은 해석기 입력으로만 쓰고 저장소에는 합성 문장만 |
| 해석기(LLM)가 문의에서 뽑아 제안한 사실. 검증 전 | 후보 사실 / candidate fact | `CandidateFact` (relation · args · provenance · confidence) | 추출 결과, 엔티티 | 관계 네 개(`asks_about` · `about_registration` · `about_session` · `about_event`)만 허용. 규칙이 파생한 사실과 구분한다 |
| 후보 사실이 어디서 왔는지 (원문 인용) | 근거 출처 / provenance | `Provenance(source, quote)` | — | 없으면 입력에서 거부 |
| 시스템이 남긴 사건 기록 (발송 · 결제 시도 · 수신증 등) | 이벤트 로그 / event log | `log_event(id, reg, kind, ts)` · `log_attr(id, key, value)` | 히스토리 | 합성 로그만. `status_event`(신청 상태)와 다르다 |
| 규칙이 문의에서 가려낸 원인 | 원인 / cause | `cause(q, cause, evidence)` | 결론 | 유형 규칙이 파생. 한 문의에 원인이 하나일 때만 accept |
| 문의 판정 결과 | 판정 / verdict | `Verdict` (`accept` · `ask` · `abstain` · `reject`) | 답변 | [design.md 13](design.md#13-운영-문의-판정-①-rulestriagedl-harnesspy) |
| 질문이 가리키는 신청 | 질문 대상 / subject | `subject(q, reg)` | — | `about_registration`이거나 `about_event`의 로그가 속한 신청 |
| 문의 유형 하나를 판정하는 규칙 묶음 | 유형 규칙 / type rule | `rules/triage.dl` 유형 1~7 (`user_input` · `external_delay` · `external_failure` · `policy_normal` · `expired` · `suspected_bug` · `seat_full`/`over_capacity` · `sync_lag`) | 분류기 | 주제별로 `cause`와 `needs`를 파생. [design.md 13](design.md#13-운영-문의-판정-①-rulestriagedl-harnesspy) |
| 규칙으로 설명할 수 없어야 정상인 조건. 깨지면 버그 의심 | 불변식 / invariant | `invariant_violated(reg, invariant)` | 제약 | 확정인데 결제 없음 · 기한 뒤 결제로 확정 · 속성 정원 초과. 위반은 `suspected_bug`로 사람에게 넘긴다 |
| 유형 규칙이 쓰는 설정값 | 문의 기준 / triage policy | `triage_policy(key, n)` | 임계값 | `grace_minutes`(0) · `payment_deadline_hours`(24). 운영 자료로 확인한 값 |
| `needs`를 누가 채울 수 있는지 | 확인 주체 / verifier | `NEEDS_VERIFIER` (외부 · 내부 · 질문 · 정책) | — | 외부 = 발송 업체 로그가 진실, 내부 = 관리자 기록. 출력에 괄호로 붙는다 |
| 시나리오 작성자가 적어 둔 기대 결과 | 기대 판정 / expected verdict | `ExpectedVerdict` (kind · cause · needs) | 정답 | `event-ops triage`가 실제 판정과 비교한다 |
| 자유 입력을 속성 값 후보로 바꾸는 부품 | 정규화기 / normalizer | `Normalizer` (Claude Code CLI · 가짜), `NormalizedValue(value, confidence, quote)` | 분류기, 태거 | 제안만 한다. 받아들이는 것은 규칙 |
| 정규화기가 제안한 속성 값. 검증 전 | 후보 속성 / candidate attribute | `candidate_attr(attendee, dim, value, confidence, evidence)` | — | 확신도는 0~100 정수. `attendee_attr`와 구분한다 |
| 사람이 승인한, 값 · 주제마다 그것을 뜻하는 단어 목록 | 별칭 사전 / alias dictionary | `job_group.aliases`, `triage.topic_aliases` | 동의어 사전, 키워드 | 직군은 한 값에만 걸리면 LLM 없이 확정, 주제는 해석기 프롬프트에 넣는다. 승인은 PR 리뷰 |
| 후보를 받아들이는 최소 확신도 | 확신도 기준 / confidence threshold | 정규화 `normalize_threshold(dim, min_pct)` ← `min_confidence`, 문의 판정 `triage.min_candidate_confidence` | 컷오프 | **가정값** 0.7 · 0.6. 정규화는 미만이면 `unknown` + 확인 요청, 문의 판정은 미만인 후보를 규칙에 넣지 않음 |
| 근거를 얼마나 믿을 수 있는지의 순서 | 근거 등급 / evidence tier | 명시 사실(asserted) `log/` > 추론 사실(inferred) `rule/` > LLM 추출 후보(검증 통과, extracted candidate) `candidate/` > 질문 `question/` | 신뢰도 점수, 원본 사실 · 규칙 추론 · LLM 제안(옛 이름) | "확인 불가"는 등급이 아니라 `ask` · `abstain` 판정 |
| 사람이 외부 · 내부 기록을 찾아본 결과 | 조회 결과 / lookup | `provider_lookup` · `payment_lookup`{result: found · none} | — | "기록 없음"과 "조회했는데 없음"을 구분한다. 원인 확정에는 조회 결과만 쓴다 |
| 해석기가 질문을 후보 사실로 바꾸는 부품 | 해석기 / interpreter | `Interpreter` (Claude Code CLI · 가짜) | 모델, 에이전트 | 사실을 만들지 않고 제안만 한다 |

## 상태 값

`status_event`의 `status`는 아래 다섯 값만 쓴다. 다른 값은 Python 모델이 거부한다.

| 값 | 뜻 | 자리 계산 |
|---|---|---|
| `applied` | 신청 접수 (입금 안내 전) | 세지 않음 |
| `pending_payment` | 입금 대기 | 세지 않음 (현황에 따로 표시) |
| `confirmed` | 확정 | **센다** |
| `cancelled` | 취소 | 세지 않음 |
| `refunded` | 환불 완료 | 세지 않음 |

## 속성 이름과 값 (1차)

| `dim` | `value` | 출처 |
|---|---|---|
| `gender` | `female` · `male` · `unknown` | 신청폼 |
| `job_group` | 정책 파일 `dimensions.job_group.values` (예: `engineering` · `design` · `product` · `other`) · `unknown` | 자유 입력 `job`을 정규화기가 제안, 확신도 기준 이상만 ([design.md 14](design.md#14-속성-정규화-job_group-normalizerpy-capacitydl)) |
| `age_band` | 정책 파일 `dimensions.age_band.bands`의 이름 (예: `20s` · `30s` · `40s_plus`) · `unknown` | `birth_year`에서 계산 |

## 도메인 경계 규칙

- **나이는 "기준 연도 − 출생 연도"로 센다** (연 단위 만 나이 근사. 생일이 지났는지는 보지 않는다). 계산은 `src/event_ops_engine/bands.py`만 쓴다. 기준 연도는 회차 날짜의 연도다.
- **나이 구간 경계는 `min_age ≤ 나이 ≤ max_age`** (양 끝 포함). `max_age`를 비우면 상한 없음.
- **정원과 목표는 사람 수**다. 신청 → 참가자 펼치기는 `src/event_ops_engine/facts.py`만 한다.
- **현재 상태는 `status_event` 중 가장 큰 `ts`의 상태**다. 같은 `ts`가 둘이면 입력 오류로 보고 Python 모델이 거부한다.
- **시각은 UTC epoch 초(int64)** 로 규칙에 넣는다. 날짜(`YYYY-MM-DD`)는 Asia/Seoul 자정으로, 회차 시작 시각(`"HH:MM"`)은 그 날짜의 Asia/Seoul 시각으로 해석한다. 변환은 `src/event_ops_engine/clock.py`만 한다.
- **"최근 1주"는 기준 시각 기준 7×24시간**이다 (`now - 604800 < confirmed_ts`).

## 기록

| 날짜 | 내용 |
|---|---|
| 2026-10-29 | 처음 만듦 (핸드오프 §3 용어 + 상태 값 + 경계 규칙) |
| 2026-10-31 | ① 용어 추가: 문의 · 후보 사실 · 근거 출처 · 이벤트 로그 · 원인 · 판정 · 해석기 |
| 2026-10-31 | ① 용어 추가: 질문 대상 · 유형 규칙 · 기대 판정 |
| 2026-11-02 | ① 용어 추가: 문의 기준 |
| 2026-11-02 | ① 용어 추가: 불변식 |
| 2026-11-02 | 용어 추가: 정규화기 · 후보 속성 · 확신도 기준, 속성 표에 `job_group` |
| 2026-11-02 | 부족분 · 남은 자리에 입금 대기 반영, 문의 기준 값 갱신 (#45 · #46) |
| 2026-11-07 | 홍보 중단 추가, 홍보 기준의 확인됨/가정 표시, 시작 시각 경계 규칙 (#52) |
| 2026-11-07 | 참가자 키 추가 (#78) |
| 2026-11-08 | 선택 속성 추가 (#31) |
| 2026-11-08 | 2인 신청 유형 추가 (#33) |
| 2026-11-09 | 조합 추가 (#32) |
| 2026-11-10 | 용어 추가: 비슷한 나잇대 · 나이 폭 · 확정·대기 / 신청 접수 (#91) |
| 2026-11-10 | 나이 폭에 폭 기준과 확인 요청 (#91 B) |
| 2026-11-10 | 나이 범위 제안 추가 (#91 C) |
