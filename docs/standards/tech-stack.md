# 라이브러리 · 도구 이력

웹사이트를 만들 때 **실제로 써 본** 라이브러리 · 서비스 · 도구의 이력이다. 새 프로젝트에서 무엇을 고를지, 어떤 버전 · 주의점이 있었는지 찾아보는 용도.
"기준"(어떻게 만드는가)은 [code-standards.md](code-standards.md) · [quality-standards.md](quality-standards.md)에, 여기에는 "무엇을 썼는가"만 적는다.

- 버전: 마지막으로 쓴 프로젝트에서 설치된 정확한 버전 (`package-lock.json` 기준)
- 설치: 그 프로젝트에서 쓴 명령. `--save-exact`는 버전을 고정한 것
- 새 프로젝트에 쓸 때는 최신 버전과 변경 사항(breaking change)을 먼저 확인한다

## 프레임워크 · 화면

| 이름 | 용도 | 버전 | 설치 | URL | 쓴 프로젝트 · 메모 |
|---|---|---|---|---|---|
| Next.js | React 웹 프레임워크 (정적 내보내기 `output: "export"`) | 16.3.6 | `npx create-next-app` | https://nextjs.org | LuckPlay — 16은 API · 파일 구조가 크게 바뀜. `node_modules/next/dist/docs/` 먼저 확인. Workers 무료 플랜에서는 서버 렌더링 대신 정적 내보내기 |
| React · React DOM | UI | 19.3.0 | Next와 함께 | https://react.dev | LuckPlay |
| Tailwind CSS | 스타일 (디자인 토큰을 `@theme` CSS 변수로) | 4.3.3 | `npm i -D tailwindcss @tailwindcss/postcss` | https://tailwindcss.com | LuckPlay — v4는 설정 파일 대신 CSS `@theme` |
| next-intl | 다국어 (한국어 · 영어, 언어별 주소) | 4.14.7 | `npm i next-intl` | https://next-intl.dev | LuckPlay — 정적 내보내기에서는 요청 기반 언어 감지를 쓰지 않고 언어를 명시 |
| Zustand | 브라우저 상태 (단계형 입력 임시 저장, sessionStorage 유지) | 5.0.15 | `npm i zustand --save-exact` | https://zustand.docs.pmnd.rs | LuckPlay — `persist` + `skipHydration`으로 정적 HTML과 첫 화면 불일치 방지 |
| Sonner | 토스트 (애니메이션 · 밀어 닫기 · 쌓기 · 멈춤) | 2.0.8 | `npm i sonner --save-exact` | https://sonner.emilkowal.ski | LuckPlay — `unstyled` + `toast.custom`으로 자체 디자인 유지. 마우스로 밀 때 글자 선택을 막아야(`select-none`) 밀기가 동작 |
| Pretendard | 한글 · 영문 본문 글꼴 (동적 서브셋) | 1.3.9 | `npm i pretendard` | https://github.com/orioncactus/pretendard | LuckPlay — OFL |
| Unbounded (@fontsource-variable) | 숫자 · 영문 라벨 글꼴 | 5.3.0 (파일만 사용) | `npm pack @fontsource-variable/unbounded` 후 woff2를 저장소에 | https://fontsource.org/fonts/unbounded | LuckPlay — `next/font/google`은 빌드 때 다운로드가 가끔 실패해 **파일을 저장소에 두고** `next/font/local` 사용. OFL |

## 서버 · 데이터 · 인증

| 이름 | 용도 | 버전 | 설치 | URL | 쓴 프로젝트 · 메모 |
|---|---|---|---|---|---|
| Supabase (서비스) | DB(Postgres) · 인증 · RLS | — | 대시보드 + CLI | https://supabase.com | LuckPlay — 브라우저는 읽기만(RLS가 보안 경계), 쓰기는 서버. 새 테이블 마이그레이션에 권한(GRANT) 포함 필수 |
| @supabase/supabase-js | Supabase 클라이언트 | 2.117.1 | `npm i @supabase/supabase-js --save-exact` | https://supabase.com/docs/reference/javascript | LuckPlay — PKCE 대신 코드(6자리) · `token_hash` 링크로 다른 브라우저에서도 인증되게 |
| Supabase CLI | 프로젝트 관리 | 2.117.0 | `npx --yes supabase@2.117.0` (전역 설치 안 함) | https://supabase.com/docs/guides/cli | LuckPlay — 프로젝트 전용 토큰으로만 실행 |
| Drizzle ORM · drizzle-kit | 스키마 · 마이그레이션 | 0.45.3 · 0.31.11 | `npm i -D drizzle-orm drizzle-kit postgres` | https://orm.drizzle.team | LuckPlay — 마이그레이션 SQL 생성 · 적용 |
| Hono | 작은 API 서버 (Cloudflare Worker) | 4.13.9 | `npm i hono --save-exact` | https://hono.dev | LuckPlay — 비밀값이 필요한 요청만 처리 |
| Cloudflare Workers (서비스) | 정적 파일 · API 호스팅 | — | — | https://developers.cloudflare.com/workers | LuckPlay — 무료 플랜 CPU 10ms: 서버 렌더링 대신 정적 에셋 + 작은 API |
| wrangler | Workers 배포 · 로컬 실행 | 4.137.0 | `npm i -D wrangler` | https://developers.cloudflare.com/workers/wrangler | LuckPlay — 전역 로그인 대신 프로젝트 토큰으로 실행 |

## 도메인 데이터 · 계산

| 이름 | 용도 | 버전 | 설치 | URL | 쓴 프로젝트 · 메모 |
|---|---|---|---|---|---|
| ssaju | 사주 · 만세력 계산 | 0.2.0 | `npm i ssaju@0.2.0 --save-exact` | https://github.com/golbin/ssaju | LuckPlay — 버전 고정(결과 재현). 한국 서머타임 · 1954–61 표준시 · 해외 출생 · 23시대 자시는 감싸는 코드에서 보정 (LuckPlay `src/lib/saju/`) |
| GeoNames (데이터) | 도시 · 경도 · 시간대 목록 | 덤프 2026-09 | `download.geonames.org/export/dump/` 에서 `cities15000.zip` · `KR.zip` | https://www.geonames.org | LuckPlay — 스크립트로 필요한 도시만 JSON으로 만들어 저장소에 둠(압축 40KB). CC BY 4.0 출처 표기 필요 |

## 테스트 · 품질

| 이름 | 용도 | 버전 | 설치 | URL | 쓴 프로젝트 · 메모 |
|---|---|---|---|---|---|
| Vitest | 단위 · 컴포넌트 테스트 | 5.0.1 | `npm i -D vitest @vitejs/plugin-react jsdom` | https://vitest.dev | LuckPlay — next-intl은 `server.deps.inline` 필요 |
| Testing Library (react · dom · jest-dom) | 컴포넌트 테스트 | 16.3.3 · 10.4.2 · 7.0.1 | `npm i -D @testing-library/react @testing-library/dom @testing-library/jest-dom` | https://testing-library.com | LuckPlay |
| Playwright | E2E · 스크린샷 | 1.63.0 | `npm i -D @playwright/test` | https://playwright.dev | LuckPlay — 외부 서비스는 `page.route`로 가짜 응답, 모바일 뷰포트 기준 |
| ESLint · eslint-config-next | 코드 검사 | 9.39.5 · 16.3.6 | Next와 함께 | https://eslint.org | LuckPlay |
| TypeScript | 타입 | 5.9.3 | Next와 함께 | https://www.typescriptlang.org | LuckPlay |
| Node.js | 실행 환경 | 22 (`.nvmrc`) | nvm | https://nodejs.org | LuckPlay — `engines: >=22.18` |

## 기록

| 날짜 | 내용 |
|---|---|
| 2026-09-26 | 처음 만듦 (LuckPlay에서 쓴 것 정리) |
