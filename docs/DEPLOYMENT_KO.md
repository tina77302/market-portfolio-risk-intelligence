# Render Web Service 2개 배포 준비

기준: 2026-11-03, `feature/mvp-release-readiness`. **준비만 완료: GitHub push·main 병합·Render 생성/배포 미실행.**
기존 private API 제안은 이 문서와 현재 `render.yaml`의 **공개 Web Service 2개** 구성으로 대체한다.
실제 계정/도메인은 아직 생성·확인하지 않았다. 아래 `<API_HOST>`, `<WEB_HOST>`는 입력 설명용이며 실제 설정값이 아니다.

## 서비스별 설정

저장소 `tina77302/market-portfolio-risk-intelligence`, Region `Singapore`, 자동배포 `off`.
아래 Build/Start는 `render.yaml`과 동일하다. Root Directory를 잘못 지정하면 Python 모듈과 snapshot을 찾을 수 없다.

| 항목 | Portfolio API | Next.js frontend |
|---|---|---|
| Service Type | Web Service / Python | Web Service / Node |
| 제안 이름 | mpri-portfolio-api | mpri-mvp-web |
| Root Directory | **빈칸(저장소 루트)** | **frontend** |
| Plan | Free / 512MB | Free / 512MB |
| Build Command | `pip install -r requirements.portfolio.txt && python -c 'from src.portfolio.readiness import require_snapshot; require_snapshot()'` | `npm ci && npm run build` |
| Start Command | `python -m uvicorn src.portfolio.server:app --host 0.0.0.0 --port $PORT --workers 1` | `npm run start -- --hostname 0.0.0.0 --port $PORT` |
| Health Check | `/health` | `/` |

웹 health는 API 휴면에 영향을 받지 않도록 분리했다. API의 준비 상태는 별도로 검사한다.
Blueprint 생성은 autoDeploy off여도 최초 실제 배포를 시작하므로 지금 실행하지 않는다.

## 필수 환경변수

API:

- `PYTHON_VERSION=3.14.4`
- `PORTFOLIO_API_CORS_ORIGINS=https://<WEB_HOST>`: **실제 웹 origin**으로 교체. 쉼표로 명시적 도메인 추가 가능.
  scheme+host(+필요시 port)만, 경로·끝 slash·와일드카드·localhost 금지. custom domain을 쓰면 실제 도메인도 추가.
- `PORTFOLIO_API_DOCS_ENABLED=false`: `/docs`, `/redoc`, `/openapi.json` 비활성. 분석 endpoint·health는 유지.
- `OMP_NUM_THREADS=1`, `OPENBLAS_NUM_THREADS=1`: 제한된 메모리/CPU에서 BLAS 과도한 병렬화 방지.
- `PORT`와 `RENDER=true`는 Render가 제공한다. 임의로 `PORT=8000`으로 고정하지 않는다.

웹:

- `NODE_VERSION=22.22.1`
- `PORTFOLIO_API_INTERNAL_URL=https://<API_HOST>`: **배포 완료된 API의 실제 HTTPS origin**.
  변수 이름은 기존 호환을 유지했지만 이 구성의 값은 public HTTPS다. 끝 slash는 정규화한다.
- `NEXT_PUBLIC_PORTFOLIO_API_URL`과 `PORTFOLIO_API_INTERNAL_HOSTPORT`는 **설정하지 않는다**.

`sync:false` 두 항목은 Dashboard에서 실제 주소를 입력해야 한다. API/웹 URL은 서비스 이름만으로 확정하지 않는다.
주소를 잘못 비워 두거나 localhost로 배포하면 Next 설정 검증이 실패한다. API CORS 미설정은 Render에서 허용 출처 없음으로 동작한다.
금융 데이터 API 키·`.env`·Frozen V1 모델·기존 연구 checkout은 시연 서버 실행에 필요 없다.

## 연결 및 공개 범위

브라우저 → 같은 출처 `/api/portfolio/*` → Next rewrite → 공개 **HTTPS API**.
무료 API는 private network 수신을 지원하지 않으므로 private hostport를 사용하지 않는다.
rewrite는 build 시 결정되므로 API 주소가 바뀌면 웹을 **다시 build/deploy**해야 한다.

CORS는 실제 웹 origin만 허용한다. 서버 프록시는 브라우저 CORS 적용 대상이 아니므로 proxy 동작과 CORS 검증은 별개다.
CORS는 인증/방화벽이 아니다. curl 등 비브라우저 클라이언트는 공개 API를 호출할 수 있다.
문서 endpoint를 닫았어도 분석 API 자체는 공개이며 이 변경에서 인증·rate limit을 추가하지 않았다.
공개 호출 자체를 금지해야 한다면 별도 서버 인증 또는 유료 private API 설계에 대한 추가 승인이 필요하다.

## Python 의존성과 필수 파일

`requirements.portfolio.txt`는 현재 검증된 Python 실행 의존성의 버전 고정 파일이다.
ML 학습 스택/XGBoost/scikit-learn/GPU는 제외했다. 기존 `requirements.txt`는 변경하지 않는다.
현재 엔진이 `src.portfolio.data`에서 상수를 import하며 requests/yfinance를 함께 import하므로 해당 패키지는 필요하다.
서버 구동 중 Yahoo/FRED에서 데이터를 수집하지 않는다.

저장소 루트에 다음이 반드시 포함되어야 한다:

- `src/portfolio/`, `config/portfolio-snapshot.sha256.json`
- `data/portfolio/prices.csv`, `factors.csv`, `universe.csv`, `snapshot_meta.json`, `scenarios.json`

5개 데이터 파일 합계 약580KiB, 기준일 **2026-10-23**. `Path(__file__).resolve()`로 저장소 기준 경로를 사용한다.
시작 전 build 검증 및 요청/health의 SHA 검증 실패 시 성공 점수를 반환하지 않는다.
DGS10의 기존 결측 처리·Portfolio 계산식은 그대로 유지한다.
웹에는 `frontend/public/data/`의 기존 연구 export와 운영 요약이 필요하다. 한국 2026-11-02 운영과 미국 최신 N/A 정책을 그대로 표시한다.
새 수집/추론 스케줄러가 없으므로 배포일을 데이터 관측일로 소개하지 않는다.

## 무료 512MB 및 휴면 위험

[공식 무료 정책](https://render.com/docs/free), [private network 정책](https://render.com/docs/private-network) 확인:

- 각 서비스는 15분 유휴 후 휴면, 복귀에 약1분 소요. 두 서비스가 각각 휴면할 수 있다.
- 현재 브라우저 API timeout은30초다. API cold start는 첫 분석 요청 실패/오류 안내/재시도를 일으킬 수 있다.
  코드의 timeout/금융 계산을 임의로 바꾸지 않았다. 시연 전 실제 API `/health`가200인지 기다린 후 웹을 연다.
  자산 목록 로딩 실패 시 API 기동을 확인하고 페이지를 새로고침한다. 인위적인 상시 keep-alive는 추가하지 않는다.
- 무료 instance hours는 workspace 합계 월750시간. 두 서비스 동시 실행 시 약375시간을 함께 소비하며,
  월내내 둘 다 상시 실행할 수 있는 예산이 아니다. 다른 무료 서비스 사용량도 합산된다.
- 재시작/휴면 시 로컬 변경은 소실된다. Git에 고정된 snapshot은 다시 포함되지만 런타임 데이터 갱신을 저장하는 방식은 사용하지 않는다.
- 로컬 Linux 측정: API 1 worker, compare20회/클라이언트 동시4개 후 최대 RSS **약140MiB**;
  Next production 주요 페이지/프록시 요청 후 최대 RSS **약278MiB**.
  512MB cgroup/Render free CPU/플랫폼 overhead를 적용한 테스트가 아니므로 배포 성공·부하 상한을 보장하지 않는다.
  Next build 작업의 메모리와 runtime RSS도 별개다.
- 512MB 초과/OOM 또는 긴 지연이 확인되면 로그/메모리 지표를 기록하고 유료 인스턴스로 전환할지 승인받는다.

비용: Free2개 compute는 무료 한도 내 **USD0/월**. 유료 512MB 각 약USD7 → 두 서비스 **기본 약USD14/월** 예상.
[공식 가격표](https://render.com/pricing)에서 배포 직전 확정. workspace·빌드/트래픽 초과·세금·도메인 별도.
실제 시연 안정성을 우선하면 sleep 없는 유료2개가 권장되지만 자동 유료 전환은 하지 않는다.

## 승인 후 배포 순서

1. 검증된 통합 diff/commit·서비스 공개 범위·Free 또는 유료 예산을 검토한다. 현재 로컬 브랜치는 원격에 없다.
2. 별도 승인 후에만 feature push/PR·필요한 병합을 수행한다. main 병합 없이 승인된 feature commit 배포도 가능하다.
3. API Web Service 먼저 생성: 루트 빈칸, 명령/환경변수 지정, 실제 API URL을 확인한다.
   웹 URL이 아직 없으면 CORS 빈 문자열로 모든 브라우저 origin을 닫아 둘 수 있다.
4. API `/health`와 주요 endpoint를 확인한다. 웹 Web Service를 만들고 실제 API HTTPS URL을 **빌드 전** 입력한다.
5. 실제 웹 URL을 확인하면 API CORS에 그 origin을 입력하고 재배포한다. 임시 localhost/* 값을 넣지 않는다.
   Blueprint 동시 최초 생성보다 Dashboard 순차 생성이 URL 확인에 명확하다.
6. 공개 HTTPS 웹의 `/api/portfolio/universe`, `/scenarios`, 분석/비교와 아래 검증을 실행한다.
   실제 휴대폰·KR/EN·시장별 상태·휴면 후 복귀도 확인한 뒤 URL을 공유한다.

## 검증 및 롤백

로컬 재현은 API8000, 웹3001로 수행했다. Render는 반드시 자동 제공 `$PORT`를 사용한다.

```bash
# repository root
.venv/bin/python -m pytest -q
.venv/bin/python scripts/check_demo_api.py --api-url http://127.0.0.1:8000
# frontend
npx tsc --noEmit
npm run lint
npm run test:charts
npm run test:integration
npm run test:render
npm run build
```

실제 API 기준 health200/as_of2026-10-23, universe28개, scenarios3개, before23.38%, after16.94%, 비교10행.
빈/잘못된 입력422, 신뢰하지 않는 Origin에 CORS 허용 header 없음, docs404도 확인한다.
배포 후 한국 운영40.2%/2026-11-02, 미국 최신N/A 및 과거10.0%/2026-10-02를 구분한다.

문제 시 자동배포 off 유지 → 웹/API **같은 직전 검증 release 쌍**으로 rollback → health/분석/시장 페이지 재검증.
기존 deploy ID·commit·환경변수 이름/주소와 snapshot manifest SHA를 배포 전에 기록한다(비밀값은 Git 금지).
Free rollback은 직전2개 배포로 제한된다. 이전 release가 없는 최초 배포는 서비스 중지 후 수정/재검증한다.

실제 Render 계정·DNS/TLS·휴면 복귀·512MB 메모리 제한 아래의 검증은 아직 수행하지 않았다.
