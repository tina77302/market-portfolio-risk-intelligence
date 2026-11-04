# 최종 MVP 오류 수정 및 배포 준비

검증일: 2026-11-03. **로컬 production 시연 가능. 클라우드 공개 배포는 승인·실환경 확인 대기.**
main 병합, GitHub push, 서비스 생성, 운영 배포를 이번 작업에서 수행하지 않았다.

## 통합 기준 및 팀 작업 보존

- 원격 main `8c9ec9dbc65fd312d99b58d822a8739359855dd8`까지 fetch 및 재확인.
- GitHub PR #4는 이미 merged/closed다. 기존 PR을 수정하거나 재병합하지 않았다.
- PR #5의 팀원 변경 `9d24f8a`(TLT30% What-if 예제)가 main에 포함되어 있다.
- 이전 안정화 브랜치 `feature/mvp-demo-stabilization`에서 별도 `feature/mvp-release-readiness`를 만들었다.
  기존 미커밋 안정화/진단 문서를 보존하며 최신 main으로 fast-forward 통합, 충돌/중복 cherry-pick 없음.
- Portfolio 엔진 analytics/factors/stress/whatif/snapshot/data/universe/schemas 계산 코드는 변경하지 않았다.
  API router와 health 경계에 integrity gate만 연결했다. 팀원의 새 예제·expected·demo·테스트 변경은 그대로다.
- `/tmp/mpri-preservation.json`의 이전 1,525개 파일 SHA 대조에서 달라진 기존 파일은
  upstream `reports/portfolio/findings.md`, `src/portfolio/demo.py`와 이번 API 경계 `api.py`, `server.py`뿐이다.
  Frozen V1 모델·Scaler·공식 Feature/MSI/임계값 계산·연구/OOS·원천 snapshot은 그대로다.

## 해결한 P1

| 문제 | 수정 및 확인 |
|---|---|
| 현재 holdings/평가금액 변경 후 과거 분석·Stress·What-if 유지 | 이벤트에서 즉시 분석/비교 state 제거. 재실행 안내 |
| What-if 제안 수정 후 이전 비교 유지 | 비교만 즉시 제거, 변경 없는 현재 분석은 유지 |
| 수정 전 요청의 늦은 응답이 과거 결과를 다시 표시 | 요청 시작 revision 대조. 초기 예제 요청과 일반 분석/비교 모두 오래된 응답 무시 |
| Compare만 실행하면 Hidden Risk Map과 비교 current가 다름 | 성공한 compare 응답의 current를 분석 패널에도 같은 시점에 반영 |
| 누락/수정 snapshot이 pairwise 계산 또는 plain500으로 진행 | 고정 5개 파일 SHA manifest와 대조. 누락/불일치는 503, health도 실패. 임의 보간/수정 없음 |
| API 장애/서버 오류/잘못된 JSON | network/rejected/unavailable 구분, 30초 timeout, KR/EN 안내. 구현 명령·내부 주소 노출 제거 |
| Stress 데이터 null이면 섹션 자체가 사라짐 | 결과가 없으며 계산하지 않았다는 명시적 상태 |
| 브라우저 localhost API 의존 | 기본 상대 경로 + Next 서버 rewrite. production 동일 출처를 실제 테스트 |

입력 검증은 빈 포트폴리오/미지원·중복 ticker/잘못된 합계/양수가 아닌 값/비유한 숫자를 차단한다.
프론트는 공백·대소문자를 정규화하여 중복 검사하며, 최종 API schema 검증은 유지한다.
API 응답 null Stress는 추정값을 만들지 않는다. DGS10 휴장일 결측 16개 및 회귀의 기존 제외 정책도 유지한다.

## 테스트 및 실제 수치

- 전체 Python **101 passed**, Starlette/httpx deprecation 경고 1건. main 기준 97개 + integrity 회귀 4개.
- TypeScript `npx tsc --noEmit`, eslint, `test:charts`, `test:integration`, production build 통과.
- `pip check` 통과. 공식 Render Blueprint JSON schema 검증 통과.
- 실제 uvicorn + Next production, 기본 상대 URL 프록시를 통해 샘플 분석/비교 200.
- 실제 Chromium: 9개 경로 한국어/영어 선택 상태, 모바일 360/390px, 메뉴 이동/언어 유지 확인.
- 5개 실제 포트폴리오: Hidden Risk Map 요약/위험기여도/상관행렬/팩터 표/Stress 각3개 및 What-if 10행 API 대조.
- 빈 ticker·잘못된 비중 차단, API 500/503/422·연결 중단·복구·null factor/Stress 안내 확인.
- 진행 중 응답을 지연시킨 후 입력 수정하여 과거 결과가 다시 나타나지 않는 회귀 통과.

| 샘플 | 연율 변동성(API, %) | 비고 |
|---|---:|---|
| 빅테크 before | 23.38 | NVDA 비중20%, 위험기여30.43% |
| TLT30% after | 16.94 | NVDA 비중14%, 위험기여28.37% |
| SPY100% | 15.24 | Market beta1, 기여100% |
| TLT100% | 12.99 | 단일 자산 기여100% |
| SPY60/TLT30/GLD10 | 11.09 | 각 계산·화면 일치 |

숫자는 고정 snapshot 2026-10-23 기준이다. 표시 반올림(1자리%)과 API(2자리%)의 차이는 정상이다.
후 포트폴리오 금리충격 손실률 **2.3312%**, 유의함 true로 팀원 최신 expected와 일치한다.

## 시장 상태

- 한국 운영 2026-11-02 Risk **0.40170958638191223 (40.2%)**, MSI **0.753405171**, 임계값 **1.11512479** 표시.
- 미국 최신 Risk/MSI/임계 **N/A**, reference revision 검증 보류 유지.
  별도 과거 캐시 재현 2026-10-02 Risk10.0%; OOS 종료는 2026-09-21.
- 한국 OOS 종료2026-09-16, 운영과 OOS 선택/표시 분리. 신규 수집이나 재추론을 이번에 수행하지 않았다.
- 기존 안정화 변경(운영 export 부재 오표시, 생성 시각/수집 시각 혼동, 날짜·범위 유효성 guard)도 통합 보존.

## 주요 파일

- `frontend/src/components/portfolio/portfolio-view.tsx`: 무효화/응답 경합/현재 분석 동기화.
- `portfolio-panels.tsx`, `frontend/src/lib/portfolio-{api,copy}.ts`: 결측/오류 안내 및 입력/timeout.
- `frontend/next.config.ts`, `render.yaml`, `requirements.portfolio.txt`: 서버 프록시/배포 환경.
- `src/portfolio/{api,server,readiness}.py`, `config/portfolio-snapshot.sha256.json`: 경계 검증.
- `tests/test_portfolio_readiness.py`, `scripts/check_*`: 실제 API/화면/경합 회귀.
- `docs/DEPLOYMENT_KO.md`, `docs/MVP_DEMO_KO.md`: 환경/시연/배포/복구 순서.
- `reports/operations/US_REVISION_DIAGNOSIS_KO.md`, `PORTFOLIO_MVP_QA_KO.md`:
  이전 요청에서 작성한 진단·QA를 보존했다. 과거 QA의 예제17.22%는 PR #5 이전의 역사적 결과이며 현재16.94%가 기준이다.

## 남은 오류·제약 및 배포 승인 대상

검증 범위 내 **열린 P0/P1 오류 없음**. P2는 초기 API 일부 실패 시 새로고침 필요,
엔진 methodology 원문 일부 한국어 유지, 라이브러리 deprecation 경고다.
미국 최신 보류는 정확성 정책에 따른 의도된 제한이며 오류처럼 우회하지 않는다.

배포 제안: Render Singapore의 `mpri-mvp-web` 공개 Next.js + `mpri-portfolio-api` private Python,
각0.5CPU/512MB, 자동배포 off. [공식 요금](https://render.com/pricing) 기준 **기본 약USD14/월**,
workspace·초과트래픽·빌드·세금·도메인 별도. 최종 결제 화면/예산 승인 필요.
실제 계정·기존 배포 대상은 확인되지 않아 이 구성은 제안이다.

실제 클라우드 clean build, 서비스 discovery, 메모리/동시접속 상한, DNS/TLS, 물리 휴대폰 접속은 아직 미검증이다.
정적 export 갱신은 수동 rebuild이며 시연 당일 최신 실시간 점수라고 소개하면 안 된다.
공개 snapshot 제공처의 재배포 권한은 책임자 확인이 필요하다.
승인 후 실행/검증/롤백은 [배포 가이드](../../docs/DEPLOYMENT_KO.md)에 정리했다.

## Git 포함 항목 안전 검사

기존 tracked 파일과 신규 후보 전체에서 private-key/GitHub token/AWS key 패턴을 검사했고 발견0건이다.
변경 후보의 secret assignment 패턴과 실제 로컬 `.env*` 인증값의 포함 여부도 발견0건이다(값은 출력하지 않음).
Git 추적 `.env` 없음, 신규/변경1MiB 초과 파일 없음. 가상환경·수집 원천·운영 cache·빌드·인증정보는 추가하지 않았다.
검증 요약은 `MVP_RELEASE_VERIFICATION.json`에 저장했다.

### Render 구성 후속 변경

이 보고서 본문의 private API/유료 제안은 이후 요청에 따라 Web Service2개/Free 기본 구성으로 대체되었다.
현재 설정과 실제 URL 입력·CORS·휴면/메모리 제약은 [DEPLOYMENT_KO.md](../../docs/DEPLOYMENT_KO.md),
검증 결과는 [RENDER_PREPARATION_KO.md](RENDER_PREPARATION_KO.md)를 우선한다.
