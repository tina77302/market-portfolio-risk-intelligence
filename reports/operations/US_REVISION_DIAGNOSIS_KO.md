# 미국 운영 추론 보류 정밀 진단

작성일: 2026-11-03 (Asia/Seoul). 기준: [PR #4](https://github.com/tina77302/market-portfolio-risk-intelligence/pull/4),
feature 커밋 `ca51b9529cec164fd8ae36a6916873050406b4c5`, base `d2197c47f9ad05e7759522ebd5c312e90c0bfd91`.

## 1. 결론과 판정

**미국 신규 데이터는 Frozen V1의 17개 feature/Pipeline 입력과 구조적으로 호환된다.
그러나 현재 승인된 과거 reference 일치 조건은 충족하지 못하므로 운영 추론 보류를 유지한다.**
모델을 다시 학습해야만 해결되는 문제라는 증거는 없다. 먼저 데이터 vintage·수치 차이·발표 후
도착한 관측을 분리하고, 운영 입력을 채택할 승인 절차가 필요하다.

핵심 발견은 다음과 같다.

1. SPY는 원래와 신규 수집본 모두 **수정주가 계열**에 가깝다. 비조정 Close로 잘못 바꾼 것이
   주원인은 아니다. 같은 yfinance 버전의 같은 날 수집본 사이에서도 과거 수정주가가 작게
   달라진다. CSV 파싱 오차나 단일 float32 반올림 한 번으로 전부 설명할 수 없다.
2. 작은 SPY 차이는 무조건 무해하지 않다. 고정 모델을 과거 6,330개 입력에 적용한 진단에서
   29개 날짜의 예측/leaf가 달라지고 최대 Risk Score 차이는 **5.359526%p**다.
3. 신용 차이는 기존 실제 관측값의 수정과 다르다. 2026-10-05의 기존 원천은 결측이고 연구
   cleaner가 이전 값을 이월했다. FRED vintage 조회는 당일 시점 미공개 → 다음 날 공개를
   확인한다. 이를 단순 숫자 허용 오차로 처리해서는 안 된다.
4. **이전 보고서/PR 설명의 미국 수집 기준일 2026-11-02 서술은 부정확하다.** 실제 실행 receipt와
   달력의 기준일은 **2026-10-30**이고 필수 네 원천도 모두 그날까지 확보되어 있다.
   당시 직접적인 보류 원인은 최신성 부족이 아니라 과거 reference 불일치다.
5. 학습 실행 receipt/정확한 학습 데이터 vintage는 보존되지 않았다. 학습 cutoff 2026-09-16은
   scaler 표본 수와 prefix 통계에 근거한 유력한 추정이며 확정된 provenance가 아니다.

이 문서는 허용 오차·승인 기준을 **제안**할 뿐이다. 기존 `rtol=atol=1e-9`, 공식 feature/MSI/
임계값 계산, 모델·Scaler, OOS, 운영 JSON은 변경하지 않았고 최신 Risk Score도 계산·발행하지 않았다.

## 2. 조사 범위와 증거 구분

### 기준 자료

원본 프로젝트는 `../market-stress-early-warning`이며 읽기 전용으로 사용했다.

| 표기 | 자료 | 역할 |
| --- | --- | --- |
| 원본 캐시 | 원본 `data/raw/raw_market_data.csv` | SPY/VIX ~2026-10-05, 실제 신용 spread ~10-02 |
| 원본 reference | 원본 `data/features/feature_matrix.csv` | 2001-08-02~2026-10-05, 6,330행 |
| 수집본 A | `data/operations/20261103T050902Z-a8e2ad14/us/` | PR의 최초 revision 수치 보고에 사용된 수집본 |
| 수집본 B | `data/operations/20261103T051151Z-2efd4699/us/` | 최종 운영 export/replay의 기반 receipt; 이번 주 비교 대상 |
| B 원천 | `source_SPY.csv`, `source_VIX.csv`, `source_DBAA.csv`, `source_DGS10.csv` | 실제 관측과 파생 spread의 분리 확인 |
| 추가 읽기 조회 | Yahoo 비조정 OHLC/Adj Close/기업행사, FRED vintage API | 기존 캐시와 원천 의미·발표 시점 교차 확인 |

B의 UTC 수집 성공 시각은 SPY `05:12:04.084957`, VIX `05:12:05.199165`,
DBAA `05:12:05.351040`, DGS10 `05:12:05.418257`이다(2026-11-03; KST는 +9시간).
원본 캐시의 수집 시각/당시 yfinance 버전은 확인 불가하다. 파일 mtime을 그 증거로 사용하지 않는다.

실행 환경은 PR의 분리된 추론 환경과 동일하다: pandas 3.0.6, numpy 2.5.3,
yfinance 1.7.0, scikit-learn 1.9.1, XGBoost 3.4.1, joblib 1.6.0.

### 수행 경계

- 원본 공식 계산기의 출력 경로만 임시 디렉터리로 돌려 **과거 공통 기간**을 재계산했다.
  feature·MSI·threshold·진단용 label 파일은 `/tmp`에만 생성했고 원본에 저장하지 않았다.
- 모델 영향 실험은 2001-08-02~2026-10-05에 한정했다. 그 이후 날짜에는 classifier의
  `predict_proba`를 호출하지 않았다. 최신 저장 feature의 scaler 변환·유한성만 검사했다.
- 과거 진단은 deployment 모델의 입력 민감도 비교다. 학습 구간도 포함되므로 OOS 평가,
  정확도 재검증, 운용 실적 또는 신규 실시간 예측으로 해석하면 안 된다.
- `run.py`, 원본 API/refresh, 학습기, Portfolio 수집기, 전체 테스트 suite는 실행하지 않았다.
  별도 진단 스크립트·조회 응답은 `/tmp`에만 두었다.

## 3. Yahoo SPY: 수정주가·정밀도·수익률 원인

### 3.1 수정주가 정의와 수집 설정

원본 `src/data/fetcher.py`는 `yf.download(["SPY", "^VIX"], ...)`에서 `auto_adjust`를 생략하고
`Close`를 선택한다. 당시 라이브러리 기본값은 당시 버전/receipt가 없어 확정할 수 없다.
현재 설치된 1.7.0의 `download` 기본값은 `auto_adjust=True`다.
PR provider는 `auto_adjust=True`, `threads=False`를 명시한다. `repair`/`rounding`은 현재
기본값 False이며, 별도의 cent 반올림이나 price repair를 적용하지 않는다.

설치 소스의 `utils.auto_adjust()`는 `Adj Close / Close`를 OHLC 조정비로 사용하고,
원래 `Adj Close`를 반환의 `Close`로 이름 바꾼다. **Close 자체를 다시 곱해 산출하는 것이 아니다.**
따라서 최종 Close 차이를 무조건 Python의 곱셈 순서 탓으로 설명할 수 없다.
[공식 yfinance 코드](https://github.com/ranaroussi/yfinance/blob/main/yfinance/utils.py),
[history의 조정·repair·rounding 옵션](https://github.com/ranaroussi/yfinance/blob/main/yfinance/scrapers/history.py).
온라인 main의 기본값과 설치 버전은 달라질 수 있어 실제 실행 의미는 설치 소스/서명을 우선 확인했다.

추가 읽기 조회는 `Ticker("SPY").history(start="2000-01-01", end="2026-11-03",
auto_adjust=False, back_adjust=False, repair=False, rounding=False, actions=True, keepna=True)`로
2026-11-03 05:44 UTC경 수행했다. 응답·yfinance cache는 `/tmp`에만 저장했다.

| 비교 | 결과 |
| --- | --- |
| 원본 캐시 vs 조회 비조정 Close | 6,729 공통행 중 6,717행 차이, 최대 약 57.33 USD |
| 원본 캐시 vs 조회 Adj Close | 최대 약 0.000213623 USD |
| B 수정주가 vs 조회 Adj Close | 최대 약 0.000213623 USD; 조회를 반복해도 과거 값이 완전히 고정되지 않음 |
| 조회 조정비 Adj Close/Close | 약 0.625058~1.0; 수정이 반영된 과거 구간 존재 |
| 조회 기업행사 | 비영(非零) 배당 108건, 마지막 2026-09-18; 분할 0건; 조정비가 1이 아닌 마지막 날짜 9/17 |

이는 원본도 수정주가 계열이었다는 **강한 수치 증거**다. 당시 원시 Yahoo 응답의 Adj Close,
Close, action 및 요청 옵션은 없으므로 특정 옛 요청을 완전히 재현했다는 뜻은 아니다.
배당 이후 수정주가가 과거로 조정되는 일반 가능성과 이번 작은 차이의 확정 원인은 구분해야 한다.

### 3.2 실제 차이와 반복 수집 안정성

단위는 USD/주이며, 변경행은 `abs(delta)>1e-9`로 센 진단 통계다. 승인 기준이 아니다.

| 비교 | 변경 가격 행 | 최대 절대 차이 | 마지막 변경 관측일 |
| --- | ---: | ---: | --- |
| 원본 vs A | 5,489 / 6,729 | 0.00018310546875 | 2026-06-09 |
| 원본 vs B | 5,494 / 6,729 | 0.00018310546875 | 2025-12-18 |
| A vs B | 5,540 / 6,748 | 0.000244140625 | 2026-06-09 |

기존 `us_revision_review.json`의 5,489행은 **A에 대해서는 맞다**. B는 다른 원천 hash를
가지므로 같은 숫자를 모든 재수집본에 일반화할 수 없다.

원본 vs B 가격의 최대 상대 차이는 약 `1.287785e-6`, 비율 범위는
`0.9999987122~1.0000010913`이다. 차이는 부호가 섞이고 일정한 재조정 배수 하나로 설명되지 않는다.
원본/B를 float32로 변환한 뒤 되돌리는 오차는 최대 약 `5.68e-14` USD지만,
가격 간 float32 ULP 거리는 중앙값 2, 90백분위 5, 99백분위 9, 최대 **18 ULP**다.

**확정:** 다운로드해 저장된 수치 자체가 다르다. CSV float64 파싱/저장 오차보다 훨씬 크며,
동일 숫자의 float32 캐스팅 한 번만으로 설명되지 않는다. cent 단위 반올림도 적용되지 않았다.

**추정:** Yahoo 조정가격의 유한 정밀도, 요청/백엔드별 계산·캐시 차이, 조정계수 재계산이
가능한 원인이다. 같은 환경의 연속 요청에서도 차이가 있어 라이브러리 버전 변경이 유일 원인일 수는 없다.
Yahoo 서버 원시 payload/계산 이력은 없어 각각의 기여를 확정할 수 없다.
한 번의 조정계수 변경이나 분할 오류로 단정할 증거도 없다.

### 3.3 수익률·window 파급

기존과 신규 모두 단순 수익률 `P_t/P_(t-k)-1`이며 log return 또는 퍼센트 단위(×100)로
바뀐 흔적은 없다. 수정주가를 사용하므로 배당 조정도 입력 의미에 포함된다.
가격을 전 기간 동일 양수 배수로 바꾸면 비율 feature는 대체로 불변이지만,
이번처럼 날짜별 오차가 다르면 수익률·rolling volatility·momentum·drawdown이 달라진다.

- B의 과거 비교에서 1D return 최대 차이 `1.69023825e-6`.
- 20D 연율 변동성 최대 차이 `6.12076407e-6`.
- 가격 차이의 마지막 날짜가 2025-12-18이어도 60D volatility 차이는 2026-03-18까지 남는다.
- `cummax` drawdown은 전체 과거 고점을 사용하므로 최근 60~252행만 비교해 안전성을
  판단할 수 없다. 수정된 고점이 유지되면 더 오래 영향이 지속될 수 있다.

## 4. FRED: 관측일·발표일·vintage·결측 처리

### 4.1 자료 정의와 시간 축

Credit proxy는 **일별 Moody's DBAA − 미 국채 10년 DGS10**, 단위는 **연율 퍼센트포인트**다.
1 bp는 이 단위로 0.01이다. 월별 BAA, OAS, 수익률(returns), 한국 금리로 대체하면 다른 입력이다.
DBAA는 Moody's 기업채 수익률이고 DGS10은 Treasury constant-maturity 금리다.
[DBAA 정의/원 제공처](https://fred.stlouisfed.org/series/DBAA),
[DGS10 정의/원 제공처](https://fred.stlouisfed.org/series/DGS10).

구분해야 할 시간은 (a) observation date, (b) 원 제공처의 발표 시각, (c) FRED series update 시각,
(d) vintage에서 해당 값이 알려진 날짜, (e) 이 프로젝트 HTTP 수집 시각이다.
FRED 페이지의 `Updated`는 전체 series 갱신 시각이며 모든 관측의 최초 발표 시각이 아니다.

조회 시 페이지에는 두 series 모두 마지막 관측일 **2026-10-30**이 표시됐다.
DBAA의 표시 갱신은 11/02 10:31 AM CST, DGS10은 11/02 3:16 PM CST다.
H.15는 평일 4:15pm 공개하되 휴일/Board 폐쇄일에는 공개하지 않는다고 명시한다.
이를 모든 observation이 당일 즉시 FRED에 도착한다는 보장으로 사용해서는 안 된다.
[연준 H.15 공개 일정](https://www.federalreserve.gov/releases/h15/),
[H.15 설명](https://www.federalreserve.gov/releases/h15/about.htm).

미국 DST 종료로 2026-11-02 주식시장 마감은 21:00 UTC다. PR 정책은 마감+12시간이므로
해당 관측의 예정 사용 시각은 11/03 **09:00 UTC = 18:00 KST**다. 11/03 05:12 UTC
실행의 `expectedDate`는 **10/30**, `publicationDeadline`은 **10/31 08:00 UTC**였다.
이 고정 12시간은 프로젝트의 공개 여유 정책이지 실제 발표 보장이나 FRED 규정이 아니다.

B 네 source의 마지막 실제 관측은 전부 10/30이며 중복 날짜는 0이다.
SPY/VIX 저장본에 11/02행이 없는 것은 수집 요청이 `expectedDate`까지 제한된 결과이므로
그 사실만으로 Yahoo 지연/장애를 주장할 수 없다. 이번 별도 Yahoo 읽기 조회는 11/02행을 반환했으나
운영 source/export로 편입하지 않았다. FRED는 일별 독립 발표 및 휴일 차이도 확인해야 한다.

### 4.2 10월 5일 차이는 값 수정인가, 새 관측의 도착인가

FRED `series/observations`를 observation_start=10/01, observation_end=10/05로 제한하고,
각각 `realtime_start=realtime_end`를 다음 날짜로 지정해 직접 조회했다.

| vintage 지정일 | DBAA·DGS10의 10/05행 | 이미 있던 10/01·10/02 | 해석 |
| --- | --- | --- | --- |
| 2026-10-05 | 모두 없음 | 존재 | 10/05 관측을 당일 vintage에서 사용할 수 없음 |
| 2026-10-06 | 모두 존재 | 앞 vintage와 동일 | 다음 날까지 실제 관측 도착 |
| 2026-11-02 | 모두 존재, 10/06 vintage 값과 동일 | 앞 vintage와 동일 | 조사한 표본에서 이후 수치 revision 증거 없음 |

따라서 10/05 spread **1.46**은 조사한 vintage에서 신규 도착한 관측이다.
원본 10/05 raw에는 NaN이었고 cleaner가 10/02 실제 spread **1.47**을 사용했으므로,
`Credit_Level` 차이 0.01은 **1 bp의 경제적 값 차이**이며 부동소수점 잡음이 아니다.
원본 캐시의 실제 수집 시각이 없어서 원본 결측이 반드시 발표 지연 하나 때문이었다고는
확정할 수 없다. 다만 vintage는 그 시나리오와 일치하고, 이월값과 신규 실제값을 비교하고 있다는 점은 확정된다.

현재 그래프 CSV는 최신 알려진 과거 값을 주며 원본 fetcher는 vintage를 고정하지 않았다.
원본에는 DBAA/DGS10 독립 cache가 없어 전 기간 component별 revision은 복원할 수 없다.
기존 실제 spread 6,686개는 B와 **차이 0**이나, 두 component가 상쇄되어 spread만 같았을
가능성까지 배제하는 증거는 아니다.

`series/vintagedates`도 두 series에 대해 10/01~11/02 범위를 조회했다. 두 목록에 10/06,
11/02가 있으나 이 목록은 **수정 또는 신규 관측 공개**를 모두 포함한다. 목록에 있다는 이유만으로
과거 값 correction이라고 해석하지 않는다. FRED real-time 날짜는 기본적으로 조회 당시 날짜에
의존한다. 이번 KST 11/03 조회에서 realtime=11/03은 서버가 오늘을 11/02로 판단하여 HTTP 400을
반환했고, realtime=11/02로는 성공했다. 이는 키 오류나 데이터 부재 증거가 아닌 날짜 경계 문제다.
응답의 realtime_start/end를 모든 행의 최초 공개 시각으로 읽어서도 안 된다.
[FRED real-time 의미](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html),
[observations/vintage 지정](https://fred.stlouisfed.org/docs/api/fred/series_observations.html),
[vintagedates 정의](https://fred.stlouisfed.org/docs/api/fred/series_vintagedates.html).

일별 vintage 비교는 공개 **날짜 수준의 구간**을 확인한다. 개별 observation의 정확한 최초
발표 시각/수정 사유 및 모든 과거 vintage를 완전 검증한 것은 아니다.

### 4.3 기존 정책과 영향 범위

원본 cleaner는 SPY가 실제 관측된 날을 master calendar로 삼고 VIX와 spread를
각각 `ffill(limit=5)` 한다. 개별 DBAA/DGS10을 각자 이월한 뒤 차감하는 방식이 아니다.
이월 제한은 달력 5일이 아닌 **SPY 관측 5행**이다. 연구 원본 정책은 바꾸지 않았다.

- 원본 SPY 날짜 6,729행 중 VIX 결측 0, spread 결측 **52**; 최대 5행 이월 후 잔여 결측 0.
- B가 새로 채운 원본 기간의 raw spread 결측은 **10/05 한 날짜**다.
- B component 원천은 각 7,000행; DBAA NaN 290개, DGS10 NaN 289개를 보존한다.
  이 숫자만으로 장애라고 판단하지 않고 각 금리 달력과 발표일을 확인해야 한다.
- PR는 출력 대상 날짜에서 필수 실제 원천이 모두 있는지를 별도 확인해 점수 이월을 막는다.
  그러나 feature 계산의 **과거 window 내부**에는 기존 연구의 이월 처리가 남는다.
  출력 날짜가 실제 관측이라는 사실이 과거 252개 입력 모두 당일 실측이었다는 뜻은 아니다.

10/05 하나의 이월값을 실제값으로 바꾼 반사실적 계산(모델 재학습/채택 없음)은 다음으로 전파된다.

| feature | B 보관 기간(~10/30)에서 영향 | 이후 가능한 영향 |
| --- | --- | --- |
| Credit_Level | 10/05 한 날짜 | 그 날짜에 한정 |
| Credit_1D_Change | 10/05, 10/06 | 현재/1행 lag |
| Credit_5D_Change | 10/05, 10/12 | 현재/5행 lag |
| Credit_20D_Momentum | 10/05~10/30, 20행 | rolling 20행에서 제거되면 종료 |
| Credit_252D_ZScore | 10/05~10/30, 현재 20행 | 이후 shifted 252행 분포에 남는 동안 영향 가능 |
| MSI/공식 임계값 | 당일 MSI와 이후 분포 | shifted rolling MSI, expanding 분위수의 장기 경로까지 점검 필요 |

따라서 10/05의 출력이 같았다는 이유로 10/30의 영향도 0이라고 일반화하면 안 된다.

## 5. 17개 feature·Scaler 계약 검증

`P`는 SPY 수정주가, `V`는 VIX level, `C`는 DBAA-DGS10 spread다.
`R_k(P)=P_t/P_(t-k)-1`, `MA_n`은 현재 포함 rolling 평균,
`Z(X)=(X_t-mean(X.shift(1),252,min=60))/(std(X.shift(1),252,min=60)+1e-8)`다.
rolling std는 pandas 표본 표준편차 `ddof=1`이다. 아래 순서가 artifact의 `feature_names_in_`,
공식 engineering 코드 및 PR whitelist와 **일치**한다.

변경행/최대 delta는 B와 원본을 공통 reference 6,330행에서 비교한 값이다.
변경행 판정은 현행 `isclose(rtol=1e-9, atol=1e-9)`의 반대이며 새로운 승인 조건이 아니다.

| 순서·이름 | 기존 계산식 | 불일치 행 | 최대 feature 절대 차이 | 최대 scaler 입력 변환 차이 |
| --- | --- | ---: | ---: | ---: |
| 1 SPY_1D_Return | R_1(P) | 5,580 | 1.69023825e-6 | 1.41506619e-4 |
| 2 SPY_5D_Return | R_5(P) | 5,732 | 1.93047347e-6 | 7.95800578e-5 |
| 3 SPY_20D_Return | R_20(P) | 5,865 | 1.72749455e-6 | 3.79913740e-5 |
| 4 SPY_20D_Vol | std(R_1(P),20) × sqrt(252) | 6,144 | 6.12076407e-6 | 5.74981670e-5 |
| 5 SPY_60D_Vol | std(R_1(P),60) × sqrt(252) | 6,183 | 2.91203210e-6 | 3.01489159e-5 |
| 6 SPY_Drawdown | (P-cummax(P))/cummax(P) | 5,296 | 1.24252004e-6 | 1.01397412e-5 |
| 7 SPY_20D_Momentum | P/MA_20(P)-1 | 6,096 | 1.08512042e-6 | 4.21366772e-5 |
| 8 VIX_Level | V | 0 | 0 | 0 |
| 9 VIX_1D_Change | V_t-V_(t-1) | 0 | 0 | 0 |
| 10 VIX_5D_Change | V_t-V_(t-5) | 0 | 0 | 0 |
| 11 VIX_20D_Momentum | V/MA_20(V)-1 | 0 | 0 | 0 |
| 12 VIX_252D_ZScore | Z(V) | 0 | 0 | 0 |
| 13 Credit_Level | C | 1 | 0.01 | 0.01311507 |
| 14 Credit_1D_Change | C_t-C_(t-1) | 1 | 0.01 | 0.32387478 |
| 15 Credit_5D_Change | C_t-C_(t-5) | 1 | 0.01 | 0.11796448 |
| 16 Credit_20D_Momentum | C/MA_20(C)-1 | 1 | 0.006496194 | 0.16158326 |
| 17 Credit_252D_ZScore | Z(C) | 1 | 0.10156524 | 0.06905778 |

원본 캐시를 재실행한 feature와 저장 reference의 최대 차이는 `1.21e-15`로 현행 허용 범위 안이다.
원본 데이터를 변경하지 않고 동일 공식 계산기로 재현한 결과다.

- B의 저장된 추론 feature는 6,688행, 최신일 10/30이다. 17개 열이 모두 수치·유한하며
  저장 scaler의 transform 결과도 모두 유한하다. 열 추가/누락·단위 변경·순서 변경은 확인되지 않았다.
- Pipeline은 `StandardScaler → XGBClassifier`, class order는 `[0,1]`이다.
  scaler의 mean/var/scale은 17차원이며 `n_samples_seen_=6317`이다.
  저장된 평균·scale을 그대로 사용하고 새 데이터에서 fit/fit_transform하지 않는다.
- scaler 변환은 `(x-mean_)/scale_`이다. 입력 차이는 feature별 scale로 나뉘므로
  **작은 원천 가격 차이와 작은 모델 영향은 같은 의미가 아니다.**
- booster 내부의 feature 이름은 None이다(scaler가 배열을 전달). Pipeline 입구의 이름과
  정확한 열 순서 검증이 필요하며 booster의 17열 차원만으로 schema를 보장할 수 없다.
- MSI 정규화는 feature용 Z와 다르다. 3채널(음의 21D SPY 수익률, VIX, spread)을
  shifted rolling252/min126/std+1e-8로 Z화하여 동일 가중 평균한다. threshold는
  MSI.shift(1)의 expanding/min252/90% 분위수다. feature용 min60과 혼동하지 않는다.
  [StandardScaler 정의](https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.StandardScaler.html).

### 학습 provenance의 한계

저장 scaler는 6,317표본이다. 현재 reference의 선두 6,317행은 2001-08-02~2026-09-16이며,
평균 최대 차이는 `1.5368512e-7`, 분산 최대 차이는 `1.1088529e-8`이다.
6,320행(~9/21)에서는 평균 차이가 약 0.0021423, 분산 차이가 약 0.0240247로 커진다.
9/16 cutoff의 근거는 강해지지만 6,317행에서도 완전 일치하지는 않는다.
**정확한 학습 데이터, 당시 vintage, 실행 환경, 학습 실행 시각을 복원한 것은 아니다.**
이번 학습 당시 데이터와의 비교는 저장 scaler/reference를 대리 기준으로 사용한 것이며,
실제 학습 X 전체를 확보했다는 의미가 아니다.

## 6. Frozen 모델 영향: 요인 분리 실험

공식 계산기를 동일 환경에서 네 가지 입력으로 실행하고 원본 공통 기간인 10/05까지로 제한했다.
VIX와 날짜 행을 유지한 채 SPY만, spread만, 둘 다 바꾸는 경우를 원본과 비교했다.
**이는 `/tmp`의 진단용 반사실적 실험이며 불일치 입력의 운영 채택이 아니다.**
동일 저장 모델에 동일 입력을 두 번 전달한 예측의 최대 차이는 0이었다.

| 진단 입력(원본 대비 변경) | leaf/출력 변경 날짜 / 6330 | 최대 Risk Score 차이(%p) | 0.50 경계 반전 | 최대 MSI 차이 | 최대 공식 threshold 차이 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 원본 재현 | 0 | 0 | 0 | 0 | 0 |
| SPY만 B | 29 | 5.359526 | 0 | 2.280477e-5 | 1.136871e-5 |
| spread만 B | 0 | 0 | 0 | 0.03385508 | 0 |
| SPY+spread B | 29 | 5.359526 | 0 | 0.03385508 | 1.136871e-5 |

A를 사용하면 출력 변경은 23개 날짜이며 최대 차이는 동일한 5.359526%p다.
B의 출력 변경 날짜 범위는 2001-10-04~2025-10-15다.
추정 학습 cutoff 이후의 기존 공통 기간(2026-09-17~10-05의 13행)은 출력 차이가 0이었다.
이는 **최신일 10/30의 출력 일치를 검증한 결과가 아니다**.
10/05의 spread 변경이 해당 날짜의 leaf를 바꾸지 않았어도 이후 window의 영향은 남는다.

### 작은 입력으로 큰 score 차이가 발생한 직접 증거

최대 차이는 과거 2005-01-25에서 발생했다. tree ID 80, 95, 98의 분기를 추적하면,
`SPY_60D_Vol`의 표준화 후 float32 값이 다음 동일한 분기 경계를 넘는다.

- split threshold: `-0.74338603`
- 원본 입력: `-0.7433828115463257`
- B 입력: `-0.7434021234512329`
- 입력 차이: `-1.93119049e-5`

단일 float32 반올림으로 사라지는 차이가 아니라 실제로 다른 leaf로 진행하는 차이다.
가격 차이가 미세해도 트리는 분기 경계에서 불연속이므로 score 차이도 비례해서 작다는 보장이 없다.
이번 0.50 경계 반전이 0건이었다는 사실도 score 표시의 동등성이나 향후 경계 안전성을 보장하지 않는다.
이 진단으로 새로운 precision/recall/AUC는 계산하지 않았다.

## 7. Revision 허용 오차·승인 기준 제안 (미적용)

현재 gate를 통과시키려고 일괄 `1e-6`/`1e-5`로 완화하는 것은 권장하지 않는다.
feature마다 단위/scale/경계가 다르고, 이번 SPY 차이에는 최대5.36%p의 모델 영향이 있기 때문이다.
관측된 최대18 ULP 또는 최대가격차를 그대로 새 cutoff로 삼는 것도 사후 기준맞춤이다.

| 분류 | 제안 검증/승인 기준 | 이번 판정 |
| --- | --- | --- |
| 모델·코드·schema | model/scaler/reference/code hash 동일, 이름·순서·단위·날짜·전처리 엄격 일치. 이 항목은 허용 오차 없음 | 구조·artifact 검증 통과 |
| 동일 원천의 직렬화 차이 | 원시 decimal/payload를 고정하고 독립 round-trip으로 parser 연산의 ULP 오차 상한을 먼저 증명. 허용폭은 그 계산에서 유도하고 알고리즘/라이브러리 버전과 함께 고정 | `~1e-4 USD`는 `~1e-14` 파싱 차이로 설명 불가 |
| 제공처 수정주가 재계산 | Close/Adj Close/action/조정비·request·vintage를 보존, 분할·배당 경계와 반복응답 차이 설명. 가격 오차뿐 아니라 feature/scaler·leaf·score·경계 영향 검사 | 원인 확정/명세 부족, leaf·score 변경 있어 자동 승인 불가 |
| FRED 신규 도착/실제 revision | 관측일·as-of/vintage·available_at·수집시각을 구분. 신규 관측은 결측→관측 전환으로 기록. 이전 이월값과의 차이에 숫자오차 규칙을 적용하지 않음 | 10/05는 신규 도착 증거 있음; 별도 vintage 정책 승인 필요 |
| 출력 안정성 | 재현 검증에는 같은 입력의 동일출력, 가능하면 해당 후보의 기존 전체 검증구간에서 leaf/score 동등성·경계 반전 0을 보수적 기본안으로 검토 | strict 동등성은 실패. 최근13행만의 무변경은 충분하지 않음 |
| 비동등 입력의 운영 채택 | score 허용변화량·경계 근접구간·예외 중단 조건을 모델/데이터 책임자가 **사전에** 정하고 독립 기간에서 검증. 비영(非零) 허용치는 이번 차이에 맞춰 정하지 않음 | 승인 없음; 이 문서는 허용값을 정하지 않음 |
| 공식 MSI/threshold | 동일 입력-vintage로 공식 계산을 재현. 임의 임계값·고정반올림·부분기간 expanding 재시작 금지 | 원본 재현은 통과; 신규 vintage의 과거값은 달라질 수 있음 |

형식상 `abs(new-old) <= atol_j + rtol_j*abs(old)` 같은 column별 규칙을 쓰더라도,
`atol_j/rtol_j`는 원천 정밀도와 연산오차 분석에서 산정해야 한다.
표준화후 오차 `abs(delta_x_j)/scale_j`와 실제 tree분기 margin을 함께 점검해야 한다.
이번 데이터에서 동등성이 깨졌으므로 “허용 오차 안이니 점수도 안전”이라는 자동 승인 결론은 낼 수 없다.

## 8. 해결 대안과 권장안

| 대안 | 장점 | 위험/필수 승인 | 권장 |
| --- | --- | --- | --- |
| 현행 엄격 gate 유지 + 원천별 vintage/원인 기록 강화 | 연구/모델 보존, 불명확한 자동 채택 방지 | 미국 최신 점수는 계속 보류 | **현재 적용 상태 유지** |
| 두 단계 검증: 동결 원본 재현 gate와 별도 운영 revision gate | 코드 재현 실패와 적법한 실제 관측 도착을 구분 가능 | 운영 데이터 명세·승인 주체·출력 drift 정책 필요; 기능 변경은 별도 작업 | **후속 설계의 우선 권장안** |
| 검증된 역사 anchor를 불변으로 두고 이후만 append | 기존 기준값 유지, 특정 vintage 재현 쉬움 | 배당/분할 조정계수·통화/수정주가 unit 연속성, 옛 결측/이월 고정의 의미를 검증해야 함. 최신값을 임의 splice하면 안 됨 | 조건부 대안 |
| 운영 전용 versioned full-vintage 재계산 | 최신 발표/수정값을 일관되게 사용 | 과거 파생값의 revision을 인정하는 운영 정책, drift 검증·승인 필요. OOS 덮어쓰기 금지 | 조건부 대안 |
| 비조정 Close로 교체, cents 반올림, scaler 재fit, 과거 점수 이월 | 없음（현재 목표에 부적합） | 학습 입력 의미/모델을 바꾸거나 차이를 숨김 | **채택하지 않음** |

권장 순서는 다음과 같다.

1. 현행 보류를 유지하고 이번 발견과 기준일 정정을 증거로 남긴다. 원래의 연구/OOS를 수정해
   신규 수집본에 맞추지 않는다.
2. 원본 cache를 동일 공식 계산기로 재현하는 검증은 독립적으로 고정한다. 이 검증에 실패하면
   새 운영 데이터 정책과 무관하게 중단한다.
3. 학습 receipt를 우선 확보하고, 새 운영 후보에는 source별 raw payload/hash, 일별 available_at,
   Yahoo action/조정설정, FRED vintage·이월 provenance를 부여한다.
4. 별도 승인된 후보의 source 의미·수정 원인을 먼저 검증한 뒤, 고정 모델·Scaler로 **운영 전용**
   drift 검증을 한다. OOS 지표를 다시 써서 정당화하지 않는다.
5. 사전 승인된 조건을 모두 만족한 날짜에만 최신 common observation을 발행한다. 숫자 계산이
   가능하다는 사실과 운영 채택 승인은 구분한다. 현재 문서만으로 승인했다고 간주하지 않는다.

## 9. 남은 검증 사항

- 학습 당시 raw/feature 전체 hash, 실제 학습X, 실행 receipt·환경을 확보해 scaler의6317행
  prefix 근사 일치를 정확한 provenance로 보강해야 한다. 없으면 한계를 계속 표시한다.
- Yahoo 원시 chart payload의 Close/Adj Close와 action을 연속 보관해 동일 요청·반복 응답의
  차이를 서버 조정계수·payload 정밀도·라이브러리 단계로 더 분해해야 한다.
  현재 캐시는 결과 Close만 있어 당시의 완전한 원인 역추적은 불가능하다.
- 배당/분할 경계, 장기 cummax, 60/252행 이력과 expanding threshold를 포함한 drift 검증이 필요하다.
  최근 날짜에서만 차이가 없다는 이유로 보편적 안전성을 승인하지 않는다.
- FRED 일별 vintage를 넓은 기간에 걸쳐 조사하고 최초 공개 시각의 상한/하한, 발표 휴일,
  provider별 시간대·DST, component별 revision 상쇄 가능성을 확인해야 한다.
- 10/05 실제 관측 도착의 10/06 이후 252행 파급과 신규 운영기간 classifier 영향은
  후속 승인된 진단 범위에서 확인해야 한다. 이번 작업은10/05 이후 새 점수를 만들지 않았다.
- 정적 운영 export에 기재할 시장 기준일과 “현재”의 정의를 달력/공개정책과 일치시켜야 한다.
  **기존 문서의11/02 기준일 오류는 이 문서에서 정정했으며 기존 PR/기능 코드는 수정하지 않았다.**
- 원천 이용·재배포 조건은 별도 유지한다. 공개 보고서에는 원천 전체나 인증정보를 포함하지 않는다.

## 10. 재현용 식별자 및 보존 확인

| 파일/내용 | SHA-256 |
| --- | --- |
| 원본 raw_market_data.csv | `fbe912a1dfb39cf6944b7ee5423d33ae1be41c480767ded9c8bce83533f3f771` |
| 원본 feature_matrix.csv | `d97ba9c56f691fe0fdecbda5491e6c4a9947ff7c9381ef00aaeb637d42585797` |
| US xgboost_latest.joblib / xgboost_latest_17f.joblib | `90c51c245ebe62b58f804098a7a7045b60fb64ef83da72d4c9a049cf8d5eeb0d` |
| US OOS 10D CSV | `ae7f52ea6e3dec288e44b30e9f3e6132dc7ebc516c9f699aafb697df5463bda1` |
| A source_SPY.csv | `4360bc63f42f5c008ad47a97ec1d11dd173043a2a679e5d49938a6c4a5c2c8fa` |
| B source_SPY.csv | `8527e8a77558d3ef785dd6fb26accefd6e69ef0aec72441cba1fa0f946a2a8c6` |
| B source_DBAA.csv | `af7497b5dbd2a106cd6bb180c5301725278a7fcbe619aba386c4cd0fcc1c2a4c` |
| B source_DGS10.csv | `6dc0ec72f40b17c0fdc2e09177fd73e05a7163515b04a6df1a1ecec1c2655a82` |
| B raw_market_data.csv | `7a2ef74f33dfd6197eb4135421744e17d7755c243ca64d0ebbc557531122235a` |
| scaler mean/var/scale 연결, little-endian float64 fingerprint | `5fd890d3bff2102c0e47bf1302fa5a4d25ecd915d487518d58064bed4d4d02b9` |

재계산 순서는 원본 raw 읽기 → SPY 실측일 위 기존 ffill5 → 공식 feature/MSI/threshold → 저장
Pipeline이며, 모델 비교는 과거 공통 기간에 한정했다. B의 SPY만, spread만, 둘 다 바꾸는 세 가지
반사실적 입력과 baseline을 비교했다. 실행 환경은 2절, source hash는 위 표, 조회 옵션은 3·4절에 있다.
진단용 임시 집계는 `/tmp/mpri-us-revision-analysis.json`, `/tmp/mpri-us-followup.json`,
`/tmp/mpri-us-source-probe.json`, `/tmp/mpri-us-fred-vintages.json`에 보관하지만 영구 연구 산출물은 아니다.
임시 파일은 환경 정리로 사라질 수 있어 중요한 관측·방법·hash는 본문에 기록했다.

최종 보존 검사에서 기존 보호 대상 1,525개 파일의 hash는 모두 동일하며 기존 tracked 파일도 변경되지 않았다.
새로운 저장소 파일은 **이 문서 1개뿐**이다. 모델/Scaler 재학습, 기능 코드 변경, OOS 갱신,
Portfolio 코드 변경, 운영 export 갱신, commit/push, PR 갱신, main 병합, 배포는 수행하지 않았다.
