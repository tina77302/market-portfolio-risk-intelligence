# M/PRI MVP 통합·안정화 점검 결과

점검일: 2026-11-03 (Asia/Seoul).

## 판정

**고정 스냅샷을 사용하는 로컬 MVP 시연은 가능하다. 현재 남은 P0 차단 오류는 0건이다.**
한국 운영 추론, 미국 보류/과거 기록 구분, Portfolio 실제 API·Hidden Risk Map·Stress Test·What-if,
사이드바·언어 전환·모바일 경로를 production 서버와 Chromium에서 확인했다.
실제 시연 장비/물리 휴대폰/LAN 접속의 최종 리허설은 남아 있다.
미국 최신 추론 성공이나 상용 운영·실시간 갱신 준비 완료를 의미하는 판정은 아니다.

새 제품 기능이나 Portfolio 엔진 재설계는 하지 않았다. 기존 기능의 상태 표시 오류·실행 환경을
수정하고 기존 API를 검증하는 smoke 검사와 시연 절차를 보강했다.

## 기준과 보존 경계

- fetch한 main: `d2197c47f9ad05e7759522ebd5c312e90c0bfd91`.
- PR #4: open, merged=false, head `ca51b9529cec164fd8ae36a6916873050406b4c5`.
- 신규 로컬 브랜치: **`feature/mvp-demo-stabilization`**, PR #4 head에서 시작.
- 기존 PR 브랜치/PR 본문을 변경하지 않았다. main 병합·GitHub push·배포·모델 재학습 없음.
- 이전 작업의 미커밋 `reports/operations/US_REVISION_DIAGNOSIS_KO.md`를 그대로 보존했다.
  해당 문서는 이번 안정화의 새 작성물이나 PR #4에 포함된 커밋 파일로 취급하지 않는다.
- 기존 보호 대상 data/model/report/src **1,525개 SHA-256 동일**.
- Frozen V1·Scaler·공식 feature/MSI/threshold·OOS·연구/검증 데이터·운영 JSON에 변경 없음.
- `src/portfolio/`, `data/portfolio/`, Portfolio UI/클라이언트 API/페이지 구현에도 변경 없음.
  공용 CountryCards의 상태 안내만 바뀌므로 `/portfolio`에서도 일관되게 보인다.

## P0/P1/P2 분류와 조치

P0는 주요 시연 흐름 실행 불가, P1은 잘못된 상태/날짜/언어 표시 또는 시연 환경의 중대한 제약,
P2는 우회 가능한 원문/경고/재현성 개선으로 분류했다.

| ID | 심각도 | 증거/현상 | 조치 또는 남은 일 | 상태 |
| --- | --- | --- | --- | --- |
| ENV-01 | P0 | 프로젝트 `.venv`에 fastapi/uvicorn/pytest/httpx/pydantic가 없어 README대로 API/테스트 실행 불가 | **기존 requirements** 설치로 복구. 형제 프로젝트 환경 대신 자체 `.venv`에서 API와95테스트 재확인. 시연 절차에 설치 명시 | 해결 |
| DISPLAY-01 | P1 | 한국 점수40.2%를 표시하면서 reason=null을 “운영 export 없음”으로 안내 | 상태별 공통 안내 함수 사용. CURRENT의 성공 안내와 실제 export 부재를 구분 | 해결 |
| DISPLAY-02 | P1 | 운영 카드의 날짜를 “최신 개별 원천”으로, replay generatedAt을 “수집 실행 시각”으로 표시 | “운영 스냅샷 기준 관측일”, “내보내기 생성 시각”으로 정정. 실제 source retrievedAt은 별도 유지 | 해결 |
| DISPLAY-03 | P1 | EN에서도 미국의 사용자용 보류 안내가 한국어로 표시 | 영어 보류 안내 제공. 원본 한국어 진단/학습 근거는 상세 정보에 보존 | 해결 |
| DISPLAY-04 | P1 | 한국 정상 운영 점수와 과거 breadth UNKNOWN/“추론 미연결” 문구가 구분 없이 섞임 | 과거 breadth 상태임을 명시하고 방법론 설명을 별도 운영 스냅샷 구조에 맞춤 | 해결 |
| DISPLAY-05 | P1 | 컴포넌트가 status와 무관하게 current 값을 직접 사용해 불일치 export에 대한 표시 보호가 약함 | CURRENT·expectedDate와 동일 날짜·유한한 범위 내 값만 표시. 차단/날짜 불일치/NaN 등 회귀 검사. 과거값 fallback 없음 | 해결 |
| ENV-02 | P1 | QA 장비의3000 포트가 이미 점유됨. 웹만3001로 바꾸면 기존 CORS에 걸림 | 다른 프로세스는 보존. QA는3001+명시적 CORS 설정으로 정상 완료. 표준/대체 포트 절차 문서화 | QA 해결; 실제 시연 장비 리허설 필요 |
| US-01 | P1 데이터 제약 | 미국 revision/reference 불일치로 최신 추론 보류 | 허용오차/모델/점수를 바꾸지 않음. 현재 N/A와10/02 캐시 재현,9/21 OOS를 분리해 시연 | 알려진 제약; 이번 MVP 차단 아님 |
| ENV-03 | P1 조건부 | 실제 휴대폰의 localhost는 시연PC가 아님. 모바일 emulation만 검증 | LAN API URL을 빌드 시 지정하고 CORS/bind/방화벽 확인 후 실제 기기 리허설 | 실기기 시연을 할 경우 남음 |
| UX-01 | P2 | API 초기 실패 후 자동 재시도 버튼은 없음 | 기존 오류 안내 확인. API 복구 후 새로고침하면 실제 분석 복구됨을 검증. 신규 기능은 추가하지 않음 | 우회 확인 |
| COPY-01 | P2 | 일부 API 설명/제공처 진단·학습 근거는 원문 언어 유지 | 사용자용 주요 상태/메뉴/표·버튼은 전환 확인. 원문은 근거로 유지 | 시연 비차단 |
| DEP-01 | P2 | Starlette의 httpx TestClient deprecation 경고1건, root requirements는 범위형 | 테스트 정상. 엔진 영향이 있는 의존성 정책 변경은 하지 않음. 실제 시연 전 검증 환경을 유지하고 재설치 후 다시 검사 | 시연 비차단 |

## 실제 실행 검증

### Portfolio: 실제 HTTP와 브라우저

`.venv/bin/python -m uvicorn src.portfolio.server:app`로 **이 프로젝트 환경에서** API를 구동했다.
테스트용 FastAPI TestClient뿐 아니라 실제 loopback HTTP endpoint를 호출했다.

| 검증 | 결과 |
| --- | --- |
| `/health` | 200, snapshot2026-10-23 |
| `/api/portfolio/universe` | 200,28개 자산 |
| `/api/portfolio/scenarios` | 200,3개 고정 shock |
| `/api/portfolio/analyze` before/after | 둘 다200. correlation/자산별factor/beta/risk contribution 구조 확인 |
| Hidden Risk Map | browser에서 실제 API 응답으로 표시; 초기 예시 변동성23.38%, NVDA비중20%, 위험기여30.43% |
| Stress Test | 3개 시나리오 카드 표시. 자산별 금액 합과 시나리오 총손익 일치, 각 시나리오 별도 취급 |
| What-if compare | 실제 POST200,10개 비교행. after변동성17.22%, NVDA비중14%, 위험기여28.22% |
| 오류 입력 | 비중90% 합계, 미지원ticker, 음수 평가금액 모두422 |
| 입력 UI | 합계가 틀린 비중 입력 시 Analyze 비활성; 복구 후 정상 분석/비교 |
| API 중단 | 브라우저에서 API 요청을 차단했을 때 명시적 오류 표시; 복구 후 새로고침으로 Hidden Risk Map 재표시 |
| 기존 demo | `.venv/bin/python -m src.portfolio.demo --check` 통과 |

연산 기준은 원본 `examples/portfolio/{before,after,expected}.json`과 동일한756거래일,
2023-10-19~2026-10-23이다. 엔진 공식이나 snapshot을 바꿔 예시값에 맞추지 않았다.
새 `scripts/check_demo_api.py`로 같은 HTTP 검사를 재실행할 수 있다.

### 시장 데이터 표시

- 한국: 운영 current 관측일 **2026-11-02**, Risk **40.2%**, MSI **0.753**, 공식 임계값 **1.115**.
  저장 JSON과 화면을 대조했다. 현재 칸의 값과 날짜가 일치하며 정상 안내가 보인다.
- 한국: 운영 이력 selector를 과거 날짜로 바꿔도 현재40.2%를 과거 점수로 대체하지 않는다.
  과거 OOS/breadth는 별도 영역·연구 기준일을 유지한다.
- 미국: 운영 기준일 **2026-10-30**, status **BLOCKED**, 현재 Risk/MSI/threshold/date 모두 **N/A**.
  과거 캐시 재현은 **2026-10-02 / 10.0%**, OOS 종료는 **2026-09-21**로 분리했다.
- 운영 데이터를 새로 수집하거나 미국 score를 새로 계산하지 않았다. 실제 원천 수집 시각과
  export 생성 시각을 구분했다. 공개 export에 원천 수치를 다시 추가하지 않았다.

### 페이지·언어·모바일

실제 Chromium에서 production build의 다음9경로를 열어 HTTP200, h1 렌더,
현재 경로 aria-current, 정상 nav/공통 레이아웃, 문서 가로 넘침 없음으로 확인했다.

`/`, `/portfolio`, `/korea`, `/us`, `/breadth`, `/validation`, `/cases`, `/sources`, `/methodology`.

- KR/EN 전환으로 `포트폴리오 분석`/`Portfolio Analysis`, 포트폴리오 표·버튼, 미국 보류 문구가 전환된다.
- 새로고침 뒤 EN선택과 html lang=en이 유지된다.
- 모바일360/390px에서 홈·한국·미국·Portfolio를 확인했다. 문서 scrollWidth=viewport width이며,
  긴 표는 기존 내부 scroll 컨테이너에서 처리된다.
- 모바일 메뉴에서 경로를 선택하면 메뉴가 닫히며 KR/EN 전환과 active 상태가 유지된다.
- 주요 경로와 분석·비교·언어·모바일 시나리오에서 예상하지 않은 browser pageerror/console error **0건**.
  API중단 검사의 의도된 네트워크 오류는 별도 구분했다.
- desktop한국/Portfolio와 모바일Portfolio screenshot을 직접 검토했다.

브라우저 의존 도구·공유 라이브러리는 `/tmp`에서만 사용했다. 시스템 패키지나 프로젝트 브라우저
런타임 의존성은 추가하지 않았다. 임시 screenshot/원시 QA로그는 `/tmp/mpri-*`에 있으며 Git에 추가하지 않는다.

## 자동 검증과 환경

- **Python95개 통과**, 기존 Starlette/httpx경고1건.
- TypeScript, ESLint, chart helper, 신규 운영 표시 regression, **production build 전부 통과**.
- `git diff --check` 통과.
- 1,525개 보호 파일 hash 동일, Portfolio 엔진/기존 UI파일과 운영 JSON diff 없음.
- main/PR #4의 원격 상태는 기준 그대로이며 새 브랜치는 로컬에만 있다.

검증 환경: Python3.14, Node22.22.1, Next.js16.4.3, pandas3.1.0, numpy2.5.4,
FastAPI0.162.0, uvicorn0.54.0, pydantic2.14.2, pytest9.2.0, httpx0.28.1, Starlette1.10.0.
이 API환경은 별도 Frozen V1 추론환경의 라이브러리를 변경한 것이 아니다.

## 변경 파일

- `frontend/src/lib/operational-status.ts`: 상태 안내/검증된 current 표시 경계의 공통 함수.
- `frontend/src/components/{operational-market,research-panels}.tsx`: 기존 화면에 공통 함수 적용,
  생성 시각/기준일/이력 표시 문구 정정. 데이터와 inference 계산은 그대로다.
- `frontend/src/lib/dashboard-copy.ts`: 과거 breadth와 운영 snapshot 설명의 모순 해소.
- `frontend/scripts/check-demo-data.mjs`, `frontend/package.json`: 의미 있는 표시 회귀 검사와 실행 명령.
- `scripts/check_demo_api.py`: 기존 API의 실제 HTTP/고정 예시 smoke 검사.
- `frontend/README.md`, `docs/MVP_DEMO_KO.md`: 두 프로세스·포트/CORS·설치·점검·시연 시나리오.
- `reports/mvp/`: 이 점검 결과와 축약 검증 기록.
- 프로젝트 `.venv`의 기존 requirements 의존성 복구는 Git에 포함되지 않는 로컬 환경 변경이다.

## 3~5일 내 마무리 권장 순서

1. 이번 P0환경 복구/P1표시 수정본을 실제 시연PC로 옮겨 설치·실행·API smoke를 재확인한다.
   승인 전 GitHub push/main 병합/배포는 진행하지 않는다.
2. 2~3일차에는 docs의5~8분 순서를 반복하고, 시연에 사용할 언어·해상도·네트워크를 확정한다.
   실기기 모바일을 보여줄 경우 URL/CORS 리허설을 이때 끝낸다.
3. 마지막1~2일은 고정 snapshot/환경을 유지하고 API재시작·새로고침 복구만 리허설한다.
   미국 revision 수용·새 추론·신규 기능·재학습은 이번 시연 범위에 넣지 않는다.

실행과 복구 절차: [MVP_DEMO_KO.md](../../docs/MVP_DEMO_KO.md).

최종 통합 기준은 [MVP_RELEASE_READINESS_KO.md](../operations/MVP_RELEASE_READINESS_KO.md) 참조.
이 문서 본문의 예제 수치는 PR #5 이전 기록이다. 현재 TLT30% 예제는 after 변동성16.94%다.
