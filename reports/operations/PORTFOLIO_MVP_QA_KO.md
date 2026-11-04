# Portfolio MVP 실제 동작 QA

점검일: 2026-11-03 (Asia/Seoul).
작업 브랜치: `feature/mvp-demo-stabilization`.
기준 커밋: PR #4 head `ca51b9529cec164fd8ae36a6916873050406b4c5`와 현재 브랜치의 기존 미커밋 안정화 변경.

## 1. 판정

**검증된 고정 snapshot과 정상 API 환경에서 Portfolio MVP 시연이 가능하다. P0는 발견하지 않았다.**
실제 `/portfolio`에서 5개 샘플을 입력해 Hidden Risk Map·Stress Test·What-if를 실행했고,
표시값을 실제 API JSON과 대조했다. 빈 포트폴리오/잘못된 입력, API 중단·500·422,
nullable 데이터의 UI 처리도 확인했다.

단, 중요한 P1이 남아 있다. 입력을 바꾼 뒤 Analyze를 생략하고 Compare만 누르면
상단 분석 패널과 비교표가 서로 다른 입력의 결과를 나타낸다. 실제 가격 결측에 대한 명시적
분석 중단/품질 안내도 부족하다. 이 때문에 모든 예외 상황에 대한 운영 준비가 끝났다는 판정은 아니다.

이번 범위는 **P0만 최소 수정**이므로 P1/P2는 기록하고 기능 코드는 수정하지 않았다.
이 작업에서 새로 추가한 저장소 파일은 **이 보고서 1개**이며, 이전 안정화 작업의 변경을 보존했다.

## 2. 검증 환경과 범위

- API: 이 프로젝트 `.venv/bin/python -m uvicorn src.portfolio.server:app --host 127.0.0.1 --port 8000`.
- 웹: 기존 production build를 `http://127.0.0.1:3001`에서 실행.
- frontend 기본 API 주소: `http://localhost:8000`; API CORS에 QA origin `http://127.0.0.1:3001`을 명시.
- 브라우저: 실제 Chromium, 데스크탑1440px 및 모바일360/390px emulation.
- 데이터: `data/portfolio/`의 기존 frozen snapshot. as_of **2026-10-23**,
  분석 window **2023-10-19~2026-10-23, 756거래일**.
- Python3.14, Node22.22.1, Next16.4.3, pandas3.1.0, numpy2.5.4,
  FastAPI0.162.0, uvicorn0.54.0, pydantic2.14.2, pytest9.2.0, httpx0.28.1.
- 외부 시장 수집·모델 추론·재학습·snapshot 재생성은 하지 않았다.

실제 HTTP 호출과 브라우저 검증을 우선 사용했다. 데이터 누락은 별도 Python 프로세스의
`TestClient(raise_server_exceptions=False)`에서 loader를 일시 대체해 주입했다.
웹의500/422/nullable 응답은 Playwright request interception으로 재현했다.
**원본 파일을 삭제하거나 누락값을 실제 snapshot에 기록하지 않았다.**
임시 코드·응답·브라우저 도구는 `/tmp`에만 두었고 제품 의존성도 새로 추가하지 않았다.

## 3. `/portfolio`와 실제 API 연결

| 경로 | 결과 | 확인 내용 |
| --- | --- | --- |
| `/portfolio` | 200 | hydration 이후 실제 API 응답으로 초기 분석 표시 |
| `GET /health` | 200 | status=ok, as_of=2026-10-23 |
| `GET /api/portfolio/universe` | 200 | 지원 자산28개 |
| `GET /api/portfolio/scenarios` | 200 | equity_selloff/rate_shock/volatility_shock 3개 |
| `POST /api/portfolio/analyze` | 5개 샘플 모두200 | allocation, concentration, correlation, factor, risk contribution, stress |
| `POST /api/portfolio/compare` | 200 | current/proposed와 비교10개 행 |
| OPTIONS preflight | 200 | QA origin 및 JSON POST 허용 |

API 내부 함수를 호출한 결과만으로 연결 성공을 판단하지 않았다. 실제 브라우저의 Analyze/Compare
버튼이 보낸 HTTP 응답을 읽고 독립 HTTP 호출 결과 및 DOM을 대조했다.

## 4. 실제 샘플과 계산 결과

평가금액은 모두 USD100,000이다. 원본 before/after 예시와 기대 결과는 변경하지 않았다.

| 샘플 | 비중 | API 연율 변동성 | Hidden Risk Map 표시 |
| --- | --- | ---: | ---: |
| before: 빅테크 집중 | AAPL30/MSFT30/NVDA20/AMZN20 | 23.38% | 23.4% |
| after: 분산 제안 | AAPL21/MSFT21/NVDA14/AMZN14/TLT10/GLD10/XLV10 | 17.22% | 17.2% |
| SPY 단일 | SPY100 | 15.24% | 15.2% |
| TLT 단일 | TLT100 | 12.99% | 13.0% |
| 균형형 | SPY60/TLT30/GLD10 | 11.09% | 11.1% |

각 샘플을 웹 편집기로 입력해 Analyze를 누르고 API와 동일한 결과인지 확인했다.
before의 NVDA 투자비중/위험기여는 **20.00%/30.43%**, after는 **14.00%/28.22%**다.
SPY/TLT 단일 자산은 위험기여100%이며, 해당1×1 correlation도 표시된다.

### Hidden Risk Map·팩터의 표시 대조

- 5개 샘플의 요약4개 값(변동성·최대 자산/분류 비중·market beta),
  자산별 비중/위험기여, correlation **76개 cell**, factor **21개 행**을 API 응답과 대조했다.
- API의 percentage 단위를 frontend가 다시100배 하는 오류는 없었다.
- 주 요약과 risk 기여도는 주로 소수1자리, correlation은2자리,
  What-if percentage는2자리로 표시된다. API23.38%와 요약23.4%는 **표시 반올림 차이**다.
- 팩터 표의 market beta는 원단위, 금리 열은 beta×10,000,
  VIX 열은 beta×1,000의 퍼센트 수익률로 표시되며 표의 +100bp/+10pt 정의와 맞는다.
- 실제 API가 반환한 자산별 beta와 포트폴리오 beta를 UI 행별로 대조했다.
  서버에서 계산한 t값/유의성 정책을 바꾸지 않았다.

### Stress Test

before/after의 실제 API 손익은 아래와 같다. **양수=손실, 음수=이익**이다.

| 시나리오 | before 손실률 | before 손실액 USD | after 손실률 | after 손실액 USD |
| --- | ---: | ---: | ---: | ---: |
| 주식시장 급락 | 30.1627% | 30,162.70 | 23.0200% | 23,020.01 |
| 금리 급등 | -0.8440% | -843.97 | 0.9410% | 941.02 |
| 변동성 급등 | 26.7575% | 26,757.45 | 20.3739% | 20,373.89 |

- 5개 샘플 ×3개, 총15개 카드의 손실률·금액·손실/이익 라벨을 API와 대조했다.
  자산별 기여액48개도 UI의 부호·반올림과 일치했다.
- 각 시나리오의 자산별 rounded loss 합과 API 총액은 cent 오차 범위 내에서 일치했다.
- UI는 손익 금액을 달러 정수로 표시한다. API의 cents를 보존하지 않고 표시 반올림하는
  기존 정책이며 계산 오류가 아니다.
- before/after의 금리 시나리오는 둘 다 significant=false다. 방향을 유의한 결과로 단정하지 않는
  비유의 안내가 표시됨을 확인했다. 다른 샘플에서도 API flag에 따른 안내 유무를 대조했다.
- 시나리오별 손익만 표시하며 합산 손실을 만들지 않는다. beta×고정충격을 미래 예측으로 바꾸지 않았다.

### What-if

before와 after를 Compare했을 때 API의 current/proposed는 각각 독립 analyze 결과와 **동일**했다.
비교10개 행의 current/proposed/change를 DOM과 대조했다.

| 지표 | 변경 전 | 변경 후 | 변화 |
| --- | ---: | ---: | ---: |
| 최대 자산 비중 | 30.00% | 21.00% | -9.00%p |
| 최대 분류 비중 | 80.00% | 56.00% | -24.00%p |
| 연율 변동성 | 23.38% | 17.22% | -6.16%p |
| Market beta (API 비교표) | 1.2951 | 0.9884 | -0.3067 |

나머지6개 stress 손실률/손실액 비교행도 동일했다. change=proposed-current이며,
퍼센트 변화는 %p, currency는USD, beta는beta 단위로 표시되는지 확인했다.
이 일치 판정은 **해당 결과를 생성한 요청 기준**이다. 입력 편집 후 이전 분석 패널이 남는 문제는
아래 P1에서 별도로 기록한다.

## 5. 빈 포트폴리오·잘못된 입력

실제 HTTP로 다음12개 경우를 검사했고 **모두422**였다.

1. holdings 빈 배열
2. holdings 필드 누락
3. 비중합90%
4. AAPL/aapl 중복(정규화 후 중복)
5. 미지원NOPE ticker
6. 0 비중
7. 음수 비중
8. 음수 평가금액
9. 비유한 평가금액 Infinity
10. 11개 자산
11. Compare의 current 빈 배열
12. Compare의 current/proposed 평가금액 불일치

frontend에서도 비중 공란/합계 오류 시 Analyze가 비활성화되고 불필요한 POST가 발생하지 않았다.
마지막 자산1개는 삭제 버튼이 비활성화되어 완전한 빈 목록을 UI에서 만들 수 없고,
그 자산의 ticker를 비우면 Analyze가 비활성화된다. API를 직접 호출해 빈 배열을 보내도 거부된다.

## 6. 데이터 누락·API 오류 처리

### 실제 snapshot 검사

- 가격2,215행, 가격 결측 **0**, 날짜 중복 **0**.
- VIX 결측0, DGS10 결측16개(전체 snapshot 기준).
- 분석 window의 팩터 유효 일간쌍: market756, volatility756, rate746.
- 기존 정책은 DGS10을 임의 이월하지 않고 금리 회귀에서 해당일/다음날의 불완전한 차분을 제외한다.
  금리의 휴장일 결측과 주가 결측 오류를 같은 것으로 분류하지 않았다.

### 결함 주입 결과

| 주입 조건 | 결과 | UI/판정 |
| --- | --- | --- |
| 가격 loader가 FileNotFoundError | API500, non-JSON | 일반 오류로 종료, 가짜 분석값 반환 없음; 데이터별 품질 안내는 부족 |
| beta loader 누락 | API500, non-JSON | 위와 동일 |
| factor loader 누락 | API500, non-JSON | 위와 동일 |
| scenarios 파일 누락 | API500 | 위와 동일 |
| AAPL 수익률 한 칸 NaN | API200, window.days=756 유지 | covariance의 pairwise 계산이 진행됨. 별도 결측/표본 차이 경고 없음 → P1 |
| analyze HTTP500 | 브라우저에 API rejected 경고 | 페이지 crash 없음, 초기 분석 결과를 생성하지 않음 |
| analyze HTTP422 | 브라우저에 거부 이유 표시 | 페이지 crash 없음 |
| scenarios HTTP500 | Promise.all 초기화 실패를 경고 | 분석/자산목록을 함께 표시하지 않음; 복구 후 새로고침 필요 |
| 정상 schema의 factor_exposure=null, stress=null | Market beta N/A, Stress Test 섹션 미표시 | 페이지 crash 없음. stress 미가용 사유가 명시적이지 않은 P1 |
| API 연결 차단/복구 | 연결 오류 경고 → 복구 후 새로고침 시 정상 분석 | 실제 브라우저에서 확인 |

주가 NaN 주입은 실제 파일이 아니라 loader가 돌려주는 **복사한 수익률 DataFrame 한 칸**에만 수행했다.
원본 가격 결측0과 혼동해서 현재 데모 수치가 손상되었다고 해석하면 안 된다.
nullable 응답도 실제 원본 파일 결함이 아니라 허용된 응답 형태의 UI 내구성 검사다.

## 7. 한국·미국 및 공통 UI 통합

- 9개 경로(`/`, `/portfolio`, `/korea`, `/us`, `/breadth`, `/validation`, `/cases`, `/sources`,
  `/methodology`)가 모두200이고 공통 sidebar/active/aria-current가 맞았다.
- `/portfolio`는 같은 shell과 KR/EN 상태를 사용한다. EN 선택과 html lang은 새로고침에도 유지된다.
- 360/390px에서 홈·Portfolio·한국·미국은 문서 가로 넘침 없이 표시되며 모바일 메뉴에서
  경로 선택 후 메뉴가 닫힌다. 실물 휴대폰/LAN은 이번 검증 범위가 아니다.
- 한국은 **2026-11-02 / 40.2% / MSI0.753 / threshold1.115**를 그대로 표시한다.
- 미국은 **운영 기준10/30, BLOCKED, 현재 Risk/MSI/threshold/date=N/A**를 유지한다.
  **10/02 캐시 재현10.0%**와 **OOS 종료9/21**을 별도로 확인했다.
- Portfolio snapshot10/23과 시장 연구/운영 기준일은 동일일로 가정하지 않는다.
- 실제 정상 수치 대조 및 공통 경로 검사에서 예기치 않은 browser pageerror는 **0건**이다.

## 8. P0/P1/P2와 이번 수정 범위

P0는 유효한 시연 데이터/입력에서 핵심 시나리오 실행 불가 또는 계산·렌더 중단,
P1은 데이터 신뢰·상태 일관성·예외 안내의 중요한 결함, P2는 우회 가능한 후속 UX/환경 개선이다.

| ID | 등급 | 발견 및 재현 증거 | 이번 조치 |
| --- | --- | --- | --- |
| P0 | 없음 | 유효한5개 샘플과 정상API에서 계산·표시·비교가 모두 동작 | **기능 코드 수정0건** |
| P1-01 | P1 | 초기before 분석23.4%에서 현재 입력을SPY100%로 바꾸고 Analyze 없이 Compare하면 Hidden Risk Map은23.4%를 유지하지만 비교표 current는15.24%로 갱신됨. 실제 API current도15.24%라 각 계산은 맞지만 패널 입력 기준이 다름 | 수정하지 않음. 시연은 **입력 수정 → Analyze → Compare** 순서 사용. 후속은 분석 결과의 입력 snapshot/stale 상태를 명시하는 최소 통합안 검토 |
| P1-02 | P1 | 복사한 수익률 한 칸 결측에도200. 표본 유효성/asset별 누락 안내 없이756일 표기 유지 | 수정하지 않음. 실제 snapshot 결측0 재확인. 추후 계산 전 QA gate/유효표본 표시를 엔진 담당자와 합의 |
| P1-03 | P1 | 필수 파일/loader 누락 시 일반500, /health는 metadata만 확인 | 수정하지 않음. 시연 전 smoke 검사로 데이터 의존성 확인. 추후 구조화된 품질 오류·readiness 분리 검토 |
| P1-04 | P1 | 허용된 nullable stress 응답에서는 섹션이 사라져 unavailable의 이유가 드러나지 않음 | 수정하지 않음. 실제 frozen snapshot은3개 시나리오 정상. 후속으로 미가용 안내 검토 |
| P2-01 | P2 | 초기화 Promise.all 중 하나 실패하면 부분 성공 결과도 미표시, 자동 재시도 UI 없음 | 복구 후 새로고침으로 정상화 확인. 신규 UX는 추가하지 않음 |
| P2-02 | P2 | 일부 API 원문 설명은 한국어 유지, Starlette/httpx deprecation 경고1건 | 주요 UI언어는 정상. 엔진·dependency 정책 변경 안 함 |
| P2-03 | P2 | 실물 휴대폰/LAN 주소·CORS는 별도 설정 필요 | emulator검증 완료. 실제 시연 장비에서 최종 리허설 |

불완전 데이터/장애를 주입했을 때의 P1과 정상 시연 경로의 P0를 구분했다.
사용자 지시대로 **P1을 해결하려고 엔진 계산식·핵심 구조 또는 UI 기능을 변경하지 않았다.**

## 9. 자동 검사와 보존

- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests -q`: **95 passed**, 기존 경고1건.
- `npx tsc --noEmit`, `npm run lint`, `npm run test:charts`, `npm run test:integration`: 통과.
- `npm run build`: 통과. `/portfolio`, `/korea`, `/us`를 포함한 production 경로 생성 확인.
- P0수정이 없으므로 이전에 검증한 기능 코드를 변경하지 않았다. 이번 시작 시 기록한
  기존 tracked/untracked 파일의 hash와 대조해 모두 그대로임을 확인했다.
- 기존 모델·연구·Portfolio 보호 파일 **1,525개 SHA-256 동일**.
- 미국 inference 허용오차·보류 정책, 원천 데이터·운영 JSON·Frozen V1·Scaler·OOS 변경 없음.
- PR #4 및 main을 수정하지 않았고 commit·GitHub push·병합·배포도 하지 않았다.

### 재현과 증거 위치

기존 `scripts/check_demo_api.py`와 `docs/MVP_DEMO_KO.md`의 실행 절차를 사용할 수 있다.
이번 확장 QA 임시 집계는 다음에 있다. 이 파일들은 Git에 추가하지 않았고 임시 정리 시 사라질 수 있으므로,
중요 결과·조건·수치는 본문에 기록했다.

- `/tmp/mpri-portfolio-qa-api.json`:5개 전체 API 응답,12개 입력 오류,실제 snapshot QA,결함주입 결과.
- `/tmp/mpri-portfolio-qa-browser.json`:sample별 DOM/API 대조와 예외 UI 검사.
- `/tmp/mpri-portfolio-qa-stale-panel.json`:P1-01의 실제23.4%/15.24% 불일치 재현.
- `/tmp/mpri-mvp-browser-final.json`:9개 경로,언어/모바일,시장 표시,API 단절·복구 검사.

**시연 전 필수 순서:** API/웹 시작 → smoke 검사 → snapshot 날짜 설명 → 입력 수정 시 Analyze 실행 →
Hidden Risk Map/Stress Test → Compare. 미국 최신 추론 성공을 시연 항목으로 넣지 않는다.

## 후속 P1 수정 (2026-11-03)

이 문서 본문은 수정 전 QA 기록이다. 현재 P1 조치/팀원의 TLT30% 예제 반영 결과와 배포 준비는
[MVP_RELEASE_READINESS_KO.md](MVP_RELEASE_READINESS_KO.md)를 기준으로 한다.
기존 결과 무효화·응답 경합·비교 current 동기화·snapshot 누락503·null Stress 안내를 수정했다.
기존 엔진 계산식은 그대로이며 현재 after 변동성은 팀원 PR #5 기준16.94%다.
