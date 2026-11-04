# Portfolio 계산·통합 검증

기획안 8장의 Portfolio·Integrated 완료 기준은 모두 아래 테스트와 점검으로 확인했습니다. 추정 대비 실제 손실도 [Stress 검증](stress_validation_report.md)으로 확인했고, 남은 항목은 발표자료입니다.

- 기준: 2026-10-23 스냅샷, 756거래일(2023-10-19 ~ 2026-10-23), 2026-11-03 점검
- 자동 테스트: 포트폴리오 테스트(`tests/test_portfolio_*.py`) 141개 통과(2026-11-04 main, Stress 검증 테스트 포함). 2026-11-03에는 아무것도 설치되지 않은 `python:3.12-slim`에 `requirements.txt`만 설치해 당시 75개가 통과하는 것도 확인했습니다.
- 시연 수치: `python -m src.portfolio.demo --check` 통과(`examples/portfolio/expected.json`)

다시 확인하는 방법:

```bash
python -m pytest -q tests/test_portfolio_*.py
python -m src.portfolio.demo --check
cd frontend && npm run build
```

## 1. 완료 기준별 근거

| 기획안 완료 기준 | 근거 (테스트·점검) |
| --- | --- |
| 지원 자산과 비중을 입력할 수 있다 | `test_universe_*`(28개 자산, 중복·빈 값 거부). `test_invalid_portfolio_is_rejected`: 합계 99%, 11개, 미지원 티커, 중복, 비중 0, 빈 목록은 모두 422. `test_value_must_be_positive`, `test_non_finite_value_is_rejected`. 화면에서 합계 99% 입력 시 경고와 "분석" 버튼 비활성화 확인 |
| 자산·섹터 집중도를 확인할 수 있다 | `test_sector_and_concentration`, `test_spy_only_portfolio_is_fully_concentrated`, `test_etf_sector_weights_explain_that_holdings_are_not_expanded` |
| Correlation을 확인할 수 있다 | `test_correlation_matrix_is_square_with_unit_diagonal`. 화면 히트맵 확인 |
| 주요 Factor Sensitivity가 계산된다 | `test_betas_recover_known_sensitivities`(가짜 데이터에 넣은 베타 1.5, −0.001을 되찾음), `test_missing_rate_day_drops_only_from_rate_regression`, `test_portfolio_exposure_is_weighted_sum_in_allocation_order`, `test_portfolio_t_stat_comes_from_regressing_portfolio_returns`, `test_perfect_fit_has_no_t_value_but_counts_as_significant` |
| 세 가지 고정 Stress Scenario의 추정 P&L이 계산된다 | `test_scenarios_pick_worst_ten_day_moves`, `test_loss_sign_and_factor_units`, `test_scenario_uses_only_its_own_factor_beta`, `test_scenarios_are_evaluated_separately_without_a_combined_total`, `test_spy_only_stress_equals_the_market_shock`, `test_tlt_only_portfolio_loses_when_rates_rise` |
| 평가금액 기준 추정 손실액을 확인할 수 있다 | `test_total_reconciles_with_rounded_asset_amounts`, `test_half_cent_rounding_preserves_loss_and_gain_signs`, `test_gains_offset_losses`, `test_every_holding_needs_exactly_one_beta` |
| 비중 변경 시 동일한 기준으로 위험이 재계산된다 | `test_compare_rows_match_each_side_of_the_analysis`, `test_compare_requires_the_same_portfolio_value`, `test_compare_validates_each_portfolio` |
| 현재 Portfolio와 변경 Portfolio를 비교할 수 있다 | `test_compare_returns_both_analyses_and_plan_rows`(기획안 2.15 행), `test_moving_into_treasuries_trades_equity_loss_for_rate_loss`, `test_rate_trade_off_is_significant_only_after_moving_into_treasuries` |
| Market → Portfolio → Stress → What-if 흐름이 연결된다 | `/portfolio` 화면 STEP 1~6을 실제 브라우저로 끝까지 실행(분석과 비교 요청 성공, 콘솔 오류 없음). 사이드바 "포트폴리오 분석" 메뉴(PR #4) |
| 데이터 기준일·계산 가정·검증 방법·분석 한계를 확인할 수 있다 | `test_methodology_is_consistent_across_endpoints`, `test_stress_significance_follows_the_portfolio_beta`. 화면에 데이터 기준일, 추정 기간, 시장·포트폴리오 기준일 차이, 해석 한계 목록 표시(한/영). 추정 대비 실제 손실은 [Stress 검증](stress_validation_report.md)(고정 위기 3구간 + 겹치지 않는 10거래일 145구간, 충격 시작 전 베타만 사용) |
| 전체 사용자 흐름을 시연할 수 있다 | 새 Python 환경에서 API 실행 확인. 실행 순서와 시연 대본은 [docs/PORTFOLIO_DEMO.md](../../docs/PORTFOLIO_DEMO.md) |

## 2. 다른 방법으로 다시 계산해 맞춰 본 것

계산 엔진과 다른 경로로 같은 값을 구해서 일치하는지 봤습니다.

| 대상 | 다른 계산 방법 | 결과 |
| --- | --- | --- |
| 연율 변동성, NVDA 위험 기여도 | 공분산 행렬 없이 일간 포트폴리오 수익률로 직접 계산 (`test_demo_matches_reference_and_direct_daily_portfolio_returns`) | 소수점 2자리까지 일치 |
| 포트폴리오 베타 | 포트폴리오 일간 수익률을 팩터에 직접 회귀 | 자산 베타 가중합과 일치 |
| SPY 100% 주식 급락 손실 | 베타 1 × 충격 −23.29% | 23.29%, $23,290 정확히 일치 |
| TLT 금리 민감도 | 듀레이션 직관(장기국채는 금리 상승에 손실) | +100bp당 −14.1%, t −64 |
| 자산별 손실 합계 | 센트 단위로 반올림한 자산별 금액의 합 | 총 손실액과 일치 |

## 3. 화면 점검 (브라우저)

Playwright로 실제 페이지를 열어 확인했습니다. 스크립트는 리포에 넣지 않았습니다.

| 상태 | 확인 내용 |
| --- | --- |
| 데스크톱 한국어 (1440px) | STEP 1~6, 차트, 히트맵, Stress 카드, 비교표 표시 |
| 영어 모드 | 화면 문구가 영어로 바뀌고, API의 고정 한국어 설명도 영어로 표시. 미국 카드 안 A의 운영 사유 문구는 원문 유지 |
| 모바일 (390px) | 가로 넘침 없음(`scrollWidth` = 화면 너비) |
| 비중 합계 오류 | 합계가 빨갛게 표시되고 메시지가 나오며 분석 버튼 비활성화 |
| API 꺼짐 | 대시보드 프록시가 500으로 답해 "분석 데이터가 누락되었거나 서비스 응답을 확인할 수 없습니다"와 재시도 안내 표시. API 요청은 모두 대시보드와 같은 주소로 나감 |
| 입력 변경 후 | 이전 분석·비교 결과를 지우고 다시 실행하라는 안내 표시. 늦게 도착한 이전 응답이 최신 결과를 덮어쓰지 않음 |
| 유의성 | \|t\| < 2인 베타와 시나리오 결과는 흐리게, Stress 카드는 회색 + "0과 구분되지 않음" |
| 접근성 | 현재·변경 입력표의 입력칸과 삭제 버튼 이름이 서로 구분됨 |

## 4. 알려진 한계

- **Stress 추정은 손실 예측이 아닙니다 ([Stress 검증](stress_validation_report.md)):** 충격 시작 전 베타로 다시 계산하면, 변경 전 포트폴리오의 2020년 3월 주식 급락은 추정 35.0% / 실제 18.1%로 크게 잡았고, 2022년 6월 금리 급등은 추정 5.4% 이익 / 실제 12.3% 손실이었습니다(같은 기간 SPY −9.7%). 145개 평상시 구간에서 시장 베타 추정 오차(MAE)는 2.13%p로 "SPY 손실 그대로" 기준(2.34%p)과 비슷했고, 금리·변동성 단일 팩터는 네 경우 모두 "SPY 손실 그대로" 기준보다 오차가 컸고, 변경 전 금리 팩터(3.96%p)는 "손실 0%" 기준(3.82%p)보다도 컸습니다. 그래서 화면의 Stress 결과는 시나리오별 민감도 비교로만 씁니다.
- **화면 자동 테스트 없음:** 화면 점검은 수동 스크립트로 했고 CI에서 자동으로 돌지 않습니다.
- **A 영역 테스트 3개 실패:** 리포에 없는 연구 데이터(`data/processed/...`)가 필요해서 실패합니다. 포트폴리오와는 관계없습니다.
- **추정 방식의 한계:** 모든 Stress 손익은 일간 베타에 과거 10거래일 충격을 곱한 선형 추정입니다. 시나리오는 합산하지 않고, 미래 손실 예측이 아닙니다.
