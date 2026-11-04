# Render 배포 준비 결과

2026-11-03. 대상 저장소 `tina77302/market-portfolio-risk-intelligence`.
**실제 배포·GitHub push·main 병합 없음.**

## 통합 상태

작업 브랜치 `feature/mvp-release-readiness`, 이전 로컬 P1 통합 commit `b2b6818`을 기반으로 준비했다.
원격 main은 `8c9ec9dbc65fd312d99b58d822a8739359855dd8`, fetch 후 추가 변경 없음.
PR #4는 main에 이미 병합되었고 팀원 PR #5(TLT30% 예제)도 포함되어 있다.
`origin/main`과 `feature/mvp-demo-stabilization` 모두 현재 통합 브랜치의 ancestor임을 확인했다.
미커밋 안정화/P1 작업은 이전 로컬 통합 commit에 포함되어 있어 누락이나 중복 cherry-pick이 없다.

## 변경 파일

- `render.yaml`: private service 제안을 **Web Service2개, Free512MB 기본**으로 변경.
  API root는 저장소 루트, 웹 root는 frontend. 자동배포 off, API health/웹 health 분리.
- `frontend/next.config.ts`: Render에서는 실제 API HTTPS origin을 필수로 요구. localhost/빈 값/경로/인증정보가 든 URL을 거부.
  브라우저 상대주소 → Next 서버 proxy → API HTTPS 유지.
- `frontend/scripts/check-render-config.mjs`, `frontend/package.json`: 실제 Next config의 Render 주소 검증 회귀 추가.
- `src/portfolio/server.py`: Render에서는 CORS 기본 deny, 실제 HTTPS origin만 허용하도록 설정 검사.
  wildcard/localhost/path 출처 거부. docs/OpenAPI 비활성 환경변수 지원. 계산 엔진은 그대로다.
- `docs/DEPLOYMENT_KO.md`: 서비스별 명령·환경·배포 순서·무료 제한·검증·롤백을 현재 구성으로 갱신.
- `RENDER_RUNTIME_VERIFICATION.json`: 로컬 메모리·CORS·분석 검증 요약.

## 서비스 입력표

| 설정 | API | frontend |
|---|---|---|
| Type / Region | Web Service / Singapore | Web Service / Singapore |
| Root Directory | 빈칸(저장소 루트) | frontend |
| Build | `pip install -r requirements.portfolio.txt && python -c 'from src.portfolio.readiness import require_snapshot; require_snapshot()'` | `npm ci && npm run build` |
| Start | `python -m uvicorn src.portfolio.server:app --host 0.0.0.0 --port $PORT --workers 1` | `npm run start -- --hostname 0.0.0.0 --port $PORT` |
| health | /health | / |

API 필수 env: `PYTHON_VERSION=3.14.4`, `PORTFOLIO_API_CORS_ORIGINS=<실제 웹 HTTPS origin>`,
`PORTFOLIO_API_DOCS_ENABLED=false`, `OMP_NUM_THREADS=1`, `OPENBLAS_NUM_THREADS=1`.
웹 필수 env: `NODE_VERSION=22.22.1`, `PORTFOLIO_API_INTERNAL_URL=<실제 API HTTPS origin>`.
`PORT`는 Render 제공, `NEXT_PUBLIC_PORTFOLIO_API_URL`과 `PORTFOLIO_API_INTERNAL_HOSTPORT`는 미설정.
실제 호스트는 생성 후 확인해야 하며 예시 이름을 실제 URL로 단정하지 않았다.

## 파일/경로/무결성

Python clean venv에서 `requirements.portfolio.txt` 설치, API import 및 snapshot hash 검증 성공.
원본 연구 환경·ML 패키지·모델 로드 없이 실행할 수 있다. requests/yfinance는 현재 모듈 import 의존성 때문에 유지했다.
필수 snapshot5개와 SHA manifest는 Git에 이미 포함되며 `__file__` 기준 저장소 경로로 로드한다.
Portfolio snapshot2026-10-23 및 시장 JSON export의 실제 관측일을 그대로 유지한다.

이전 보호 baseline1,525개와 SHA 대조: 차이는 팀원 upstream 문서/demo2개와 이미 승인된 API 경계 api/server2개뿐이다.
Frozen V1 모델·Scaler·공식 feature/MSI/임계값·OOS·연구 결과·Portfolio 핵심 엔진·고정 원천은 변경하지 않았다.
미국 최신 추론 보류 정책과 한국 운영 점수도 변경하지 않았다.
tracked 및 신규 후보의 private-key/GitHub/AWS token 패턴 발견0, 실제 로컬 인증정보 값 포함0,
tracked `.env` 없음, 변경/신규1MiB 초과 없음. 인증값을 보고서나 로그에 출력하지 않았다.

## 검증 결과

- Python 전체 **101 passed**, 기존 Starlette/httpx deprecation1건.
- TypeScript / lint / chart / market integration / **test:render** / production build 통과.
- 공식 Render Blueprint JSON schema 통과, type:web2개 검증.
- 실제 HTTP `/health`200, universe28개, scenarios3개, analyze/compare200.
- 기본 예제 vol23.38% → TLT30%16.94%, Stress3개, What-if10행. 실제 화면과 API 수치 일치.
- 빈/잘못된 입력422, 허용 origin에만 CORS header, 미허용 origin header 없음,
  docs/redoc/openapi404, 잘못된 Render CORS 설정은 startup 거부 확인.
- P1 무효화/지연 응답/compare-current 동기화 회귀 통과.
- API 1worker/BLAS1, 비교20회·클라이언트 동시4개 로컬 테스트 성공.
  API 최대 약140MiB RSS, Next production 주요 경로/프록시 요청 후 약278MiB RSS.

이는 로컬 Linux 테스트이며 **Render512MB cgroup·실제 free CPU·DNS/TLS·휴면 재기동 검증은 아니다**.
실제 클라우드 배포 성공을 아직 확정하지 않는다.

## 무료 정책·공개 범위 및 권장안

[Render 무료 정책](https://render.com/docs/free): 15분 유휴 후 휴면, 복귀 약1분, workspace 합계750 free hours/월.
두 서비스가 함께 켜지면 약375시간을 소비한다. 현재30초 요청 timeout 때문에 cold API의 첫 요청은 실패할 수 있다.
시연 전 API health200 확인 → 웹 기동 → 실패했다면 새로고침/재분석. 상시 keep-alive는 추가하지 않았다.

무료 API는 [private network 수신 불가](https://render.com/docs/private-network)여서 public HTTPS를 사용한다.
CORS는 실제 웹 origin으로 제한하고 docs는 닫았지만, **비브라우저 접근을 차단하는 인증은 아니다**.
API 완전 비공개가 필요하면 현재 두 무료 Web Service 제약과 별도 접근 제어 요구를 재검토해야 한다.

무료한도 내 compute USD0/월. 유료512MB 각 약USD7이면 기본USD14/월 예상.
[공식 가격표](https://render.com/pricing)와 실제 결제 화면에서 확인하며 workspace/초과사용/세금/도메인은 별도다.
시연의 cold start를 피하려면 유료2개를 권장하지만 이번에 유료 선택·자원 생성은 하지 않았다.

## 다음 단계 (아직 실행하지 않음)

승인된 feature commit 공유 → API Web Service 먼저 배포/URL확정 → 웹 env에 API HTTPS URL 입력/build →
실제 웹 origin을 API CORS에 입력/재배포 → 두 공개 URL에서 health/핵심 분석/시장 구분/모바일/휴면 복귀 검증.
Blueprint는 최초 생성 즉시 실제 배포할 수 있으므로 승인 전 적용하지 않는다.
상세 순서와 직전 release 쌍 rollback 절차는 [DEPLOYMENT_KO.md](../../docs/DEPLOYMENT_KO.md)를 따른다.
