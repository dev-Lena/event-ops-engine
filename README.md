# event-ops-engine — 모임 운영 판단 엔진

회차별 신청 데이터를 **속성(성별 · 나이 구간)별 목표**와 견주어 현황을 내고, 홍보가 필요한지 판단하는 규칙 엔진입니다.
규칙은 [wirelog](https://github.com/semantic-reasoning/wirelog)(Datalog)로, 입력 변환과 근거 조립은 Python으로 씁니다.
엔진은 **권고만** 하고 실행(홍보 · 신청 처리)은 사람이 합니다.

| 문서 | 내용 |
|---|---|
| [docs/design.md](docs/design.md) | 범위 · 흐름 · 데이터 모델 · 규칙 · 보안 · wirelog 제약 |
| [docs/glossary.md](docs/glossary.md) | 용어 · 상태 값 · 도메인 경계 규칙 |
| [docs/decisions/](docs/decisions/) | 결정 기록 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 개발 기준과 이 프로젝트에서 다르게 하는 것 |

이 저장소에는 **합성 데이터만** 있습니다. 실제 모임 · 고객 · 참가자 정보는 어디에도 없습니다.

## 설치

```bash
python3.11 -m venv .venv && source .venv/bin/activate
make install
```

### Intel Mac: 엔진 빌드

2026-10 기준 `pyrewire` wheel에 Intel Mac용 엔진이 없어 한 번 소스 빌드합니다 (약 1~2분).

```bash
pip install meson ninja
make engine            # vendor/wirelog (v0.70.0) 받아서 빌드
```

빌드 결과 `vendor/wirelog/build/libwirelog.1.dylib`는 `WIRELOG_LIB` 환경변수가 비어 있으면 자동으로 잡습니다 (`.env.example` 참고). Linux CI는 wheel에 든 엔진을 그대로 씁니다.

## 사용

```bash
event-ops report data/synthetic/scenarios/pair-mixed.yaml
```

```
[회차 s2] 정원 12 · 확정 4 · 입금 대기 1 · 남은 자리 8
  age_band=20s: 확정 2 · 대기 0 · 목표 2~12
  age_band=30s: 확정 2 · 대기 0 · 목표 4~12 · 부족 2
  gender=female: 확정 3 · 대기 0 · 목표 6~6 · 부족 3
  gender=male: 확정 1 · 대기 1 · 목표 6~6 · 부족 5
  홍보 권고: 회차 임박: 30s 2명 부족, 홍보가 필요합니다. (이유: lead_time, slow_trend; 근거: session_capacity/s2, days_left/s2, target/s2/age_band/30s, policy/s2/lead_days, ...)
  홍보 권고: 회차 임박: female 3명 부족, 홍보가 필요합니다. (이유: lead_time, slow_trend; 근거: ...)
  홍보 권고: 비율 불균형: male 쪽이 5명 적습니다. (이유: imbalance, lead_time, slow_trend; 근거: ...)
```

시나리오 파일 형식은 `data/synthetic/scenarios/*.yaml`, 정책(속성 정의 · 목표 · 홍보 기준)은 `policy/events/*.yaml`을 보세요. 홍보 기준값은 모두 **가정값**입니다.

## 개발

```bash
make check     # lint(black · isort · flake8) + typecheck(mypy strict) + test(pytest)
python scripts/verify_wirelog.py   # wirelog 문법 검증 25건 (24건 통과가 정상, docs/design.md 9)
```

| 폴더 | 내용 |
|---|---|
| `rules/` | Datalog 규칙: `ontology.dl`(사실 스키마) · `capacity.dl`(② 현황) · `promotion.dl`(③ 홍보 판단) |
| `src/event_ops_engine/` | lib(`model` `bands` `clock` `facts` `policy` `loader` `decision`) · services(`engine`) · features(`capacity` `promotion` `cli`) |
| `policy/events/` | 모임 정책 YAML (합성 예시) |
| `data/synthetic/scenarios/` | 합성 시나리오 5개: 1인 · 2인 혼성 · 단체 · 1:1 비율 · 경계 |
| `tests/` | pytest (계산 로직은 같은 PR에 테스트를 올립니다) |
| `scripts/` | 엔진 빌드 · 문법 검증 |

## 라이선스

Apache-2.0. wirelog는 LGPL-3.0(동적 연결, 저장소에 포함하지 않음), PyreWire는 Apache-2.0 OR GPL-3.0.
