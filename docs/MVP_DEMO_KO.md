# M/PRI MVP 로컬 시연 절차

기준은 PR #4의 고정 운영/연구 스냅샷이다. 현재 작업 브랜치는
`feature/mvp-demo-stabilization`이며 PR #4, main, 모델, 연구 산출물을 변경하지 않는다.
시연 중 수집기·학습기·Portfolio snapshot 갱신 명령을 실행할 필요가 없다.

## 1. 실행 환경 준비

저장소 루트에서 실행한다. `.venv`가 이미 있어도 API/test 모듈이 모두 설치됐다고 가정하지 않는다.

```bash
python3 -m venv .venv              # .venv가 없는 경우에만
.venv/bin/python -m pip install -r requirements.txt
cd frontend
npm ci
```

Node/Python이 설치된 시연 장비에서 사전에 준비한다. 이번 검증은 Python 3.14,
Node 22.22.1, Next.js 16.4.3 환경에서 수행했다. 실제 검증 버전은 readiness 보고서에 있다.
위 requirements는 Portfolio API용이다. Frozen V1 추론 환경은 별도이므로 해당 환경에
의존성을 혼합 설치하거나 이 시연을 위해 모델을 다시 만들지 않는다.

## 2. 두 프로세스 실행

터미널 A, 저장소 루트:

```bash
.venv/bin/python -m uvicorn src.portfolio.server:app --host 127.0.0.1 --port 8000
```

터미널 B:

```bash
cd frontend
npm run build
npm run start -- --hostname 127.0.0.1 --port 3000
```

브라우저에서 `http://127.0.0.1:3000`을 연다. API의 기본 CORS는 localhost/127.0.0.1의
3000 포트를 허용한다. API는 기존 frontend 기본값인 `http://localhost:8000`으로 연결된다.
API와 웹 둘 다 실행해야 하며, API를 끈 상태의 정적 화면만으로 분석 기능을 시연할 수 없다.

3000이 다른 프로세스에 점유되어 있으면 그 프로세스를 종료하지 말고 대체 포트를 쓴다.
이번 QA는 다음 설정으로 3001을 사용했다.

```bash
# 터미널 A: 기존에 본인이 실행한 API만 먼저 종료한 뒤
PORTFOLIO_API_CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,http://127.0.0.1:3001 \
  .venv/bin/python -m uvicorn src.portfolio.server:app --host 127.0.0.1 --port 8000

# 터미널 B, frontend 디렉터리
npm run start -- --hostname 127.0.0.1 --port 3001
```

웹 포트만 바꾸고 CORS를 그대로 두면 페이지는 열려도 Portfolio 호출이 차단된다.
API 포트를 바꾸는 경우 `NEXT_PUBLIC_PORTFOLIO_API_URL`을 **빌드 시점**에 지정해야 한다.

실제 휴대폰/LAN에서 열 경우 폰의 localhost는 시연 PC가 아니다. PC의 LAN 주소를 API URL로
지정해 빌드하고, API CORS에는 그 웹 origin을 명시하며 서버의 bind/방화벽도 맞춰야 한다.
이는 로컬 장비 간 연결 설정이며 이번 작업에서 실제 LAN 공개/배포는 실행하지 않았다.

## 3. 시연 직전 확인

저장소 루트:

```bash
.venv/bin/python scripts/check_demo_api.py
.venv/bin/python -m src.portfolio.demo --check
.venv/bin/python -m pytest tests -q
```

frontend 디렉터리:

```bash
npx tsc --noEmit
npm run lint
npm run test:charts
npm run test:integration
npm run build
```

`check_demo_api.py`는 이미 실행 중인 API에 읽기/계산 요청만 보내고 저장된 before/after 예시와
분석·stress·what-if를 대조한다. 다른 API 주소는 `--api-url http://127.0.0.1:8000`으로 지정한다.
원천·모델·연구·Portfolio snapshot 파일에 쓰지 않는다.

## 4. 5~8분 시연 순서

1. `/`에서 한국 운영 관측일 **2026-11-02**, Risk **40.2%**, MSI **0.753**를 확인한다.
   연구 스냅샷 날짜와 운영 관측일이 다르며 실시간 갱신이 아님을 설명한다.
2. `/korea`에서 공식 임계값 **1.115**, 실제 점수 날짜와 원천별 수집 시각을 확인한다.
   운영 관측일 선택을 바꿔도 위의 현재 관측 점수가 과거 값으로 대체되지 않는지 보여준다.
   아래 OOS·breadth 연구 구간은 별도 날짜의 과거 검증이다.
3. `/us`에서 현재 점수 **N/A / 검증 보류**와 과거 캐시 추론 **2026-10-02 / 10.0%**를 구분한다.
   과거 OOS의 종료일은 **2026-09-21**이다. 최신 점수를 재현한 것처럼 설명하지 않는다.
4. 사이드바 `포트폴리오 분석`으로 이동한다. API snapshot은 **2026-10-23**이다.
   예시 AAPL/MSFT 30%, NVDA/AMZN 20%, 평가금액 USD 100,000을 확인한다.
5. Hidden Risk Map에서 연율 변동성 **23.38%**, NVDA 투자비중 **20%**와 위험기여도 **30.43%**를 비교한다.
   섹터 비중은 ETF 내부 종목을 펼친 결과가 아니라 자산 분류 기준임을 설명한다.
6. Stress Test 세 가지를 각각 확인한다. 양수=손실, 음수=이익이며 시나리오 손실을 합산하지 않는다.
7. What-if 기본 제안(기존 비중의 70% + TLT 30%)으로 `비교`한다.
   연율 변동성 **16.94%**, NVDA 투자비중 **14%**, 위험기여도 **28.37%**를 확인한다.
8. EN으로 바꿔 `Portfolio Analysis`, 표·버튼을 확인한 뒤 KR로 돌아온다.
   모바일 폭에서는 메뉴를 열고 한국/미국/포트폴리오로 이동하며 메뉴가 닫히는지 확인한다.

시장 Risk Score는 포트폴리오 손실확률이 아니다. Portfolio beta×고정충격 결과도 예측이나 보장이 아니다.

## 5. 문제가 생겼을 때

- API 연결 실패: `/health`와 터미널 A를 확인한다. 포트와 CORS를 확인하고 API 복구 후 페이지를 새로고침한다.
  기존 동작은 오류를 명시적으로 표시하며 가짜 분석 결과를 만들지 않는다.
- 분석/비교 버튼 비활성: 자산 중복, 합계100%, 양수 비중·평가금액, 최대10개 여부를 확인한다.
- 웹의 운영 점수가 오래됨: 스냅샷의 명시된 관측일을 기준으로 설명한다. 시연 직전 임의 수집/재학습으로
  결과를 바꾸지 않는다. 승인된 export를 반영해야 할 때만 재검증 후 rebuild/restart한다.
- 미국 보류: 알려진 reference/vintage 문제로, 시연의 정상적인 제한 상태다. 허용오차를 임의로 완화하지 않는다.
- 종료: 본인이 실행한 API/웹 터미널에서 Ctrl+C. 다른 작업의 서버는 종료하지 않는다.

현재 검증은 로컬 production 서버와 실제 Chromium(데스크탑·360/390px 모바일 emulation) 기준이다.
실제 시연 장비·물리 휴대폰·사내 네트워크에서는 최종 리허설을 별도로 해야 한다.

현재 배포 준비 및 동일 출처 API 프록시 설정은 [DEPLOYMENT_KO.md](DEPLOYMENT_KO.md)를 우선합니다.
