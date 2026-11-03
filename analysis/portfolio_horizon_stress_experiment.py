"""Stress 검증: direct 10-observation equity/rate return regression.

    python -m analysis.portfolio_horizon_stress_experiment

Completed, non-overlapping training blocks end strictly before each evaluation
start. Realized evaluation factors are scenario inputs, never training data.
"""

import hashlib
import json
import platform
from pathlib import Path

import numpy as np
import pandas as pd

from analysis.portfolio_joint_stress_experiment import fit_before, fit_ols, summarize
from analysis.portfolio_stress_validation import (
    CASE_NAMES, HORIZON, WINDOW, load_portfolios, markdown_table,
    realized_shock, subject_weights, validate_inputs,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/portfolio/direct_10d_stress"
MIN_BLOCKS = 25  # Approximately one trading year; never tuned on outcomes.
CANDIDATES = ("direct_10d_joint", "direct_10d_sensitivity")
LABELS = {
    "daily_joint": "첫 수정: 일간 베타", "daily_joint_with_intercept": "일간 베타+10일분 절편",
    "direct_10d_joint": "10일 직접 학습+절편", "direct_10d_sensitivity": "10일 직접 학습: 민감도만",
    "spy_proxy": "단순 SPY", "zero_loss": "0손실 기준",
}


def training_blocks(prices, factors, start, window=WINDOW):
    """End-anchor fixed 10-day blocks at the last pre-start observation.

    At most 756 daily return increments are available. Use the most recent
    floor(available / 10) complete blocks; the oldest remainder is not padded.
    Missing rate endpoints exclude a block, while missing interior levels do
    not affect an observed endpoint-to-endpoint yield change. No imputation.
    """
    pos = prices.index.get_loc(pd.Timestamp(start))
    last = pos - 1
    lower = max(0, pos - window - 1)
    count = (last - lower) // HORIZON
    if count < MIN_BLOCKS:
        raise ValueError("not enough complete pre-start 10-day blocks")
    starts = np.arange(last - count * HORIZON, last, HORIZON)
    ends = starts + HORIZON
    first_prices = prices.iloc[starts].to_numpy()
    last_prices = prices.iloc[ends].to_numpy()
    y = last_prices / first_prices - 1
    x = np.column_stack([
        y[:, prices.columns.get_loc("SPY")],
        (factors.DGS10.iloc[ends].to_numpy() - factors.DGS10.iloc[starts].to_numpy()) * 100,
    ])
    valid = np.isfinite(x).all(axis=1) & np.isfinite(y).all(axis=1)
    blocks = pd.DataFrame({
        "evaluation_start": str(pd.Timestamp(start).date()),
        "block_start": prices.index[starts].strftime("%Y-%m-%d"),
        "block_end": prices.index[ends].strftime("%Y-%m-%d"),
        "market_return": x[:, 0], "rate_change_bp": x[:, 1], "used_in_fit": valid,
    })
    return x[valid], y[valid], blocks


def fit_direct(prices, factors, start):
    x, y, blocks = training_blocks(prices, factors, start)
    beta, intercept, n, condition = fit_ols(x, y, min_observations=MIN_BLOCKS)
    used = blocks[blocks.used_in_fit]
    return {
        "beta": pd.DataFrame(beta.T, index=prices.columns, columns=["market", "rate"]),
        "intercept": pd.Series(intercept, index=prices.columns), "n": n,
        "condition": condition, "blocks": blocks,
        "train_start": used.block_start.min(), "train_end": used.block_end.max(),
    }


def replay(prices, factors, start, end, portfolios):
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    if prices.index.get_loc(end) - prices.index.get_loc(start) != HORIZON:
        raise ValueError("expected exactly 10 trading observations")
    direct = fit_direct(prices, factors, start)
    daily = fit_before(prices, factors, start)["joint_market_rate"]
    shocks = pd.Series({f: realized_shock(prices, factors, start, end, f) for f in ("market", "rate")})
    endpoint_returns = prices.loc[end] / prices.loc[start] - 1
    rows = []
    for subject, weights in subject_weights(prices, portfolios).items():
        w = pd.Series(weights).reindex(prices.columns, fill_value=0.0)
        actual = -100 * float(w @ endpoint_returns)
        common = {"subject": subject, "kind": "portfolio" if subject in portfolios else "asset",
                  "start": str(start.date()), "end": str(end.date()), "actual_loss_pct": actual,
                  "shock_market": float(shocks.market), "shock_rate": float(shocks.rate)}
        for model, fit, add_intercept, intercept_days in (
            ("daily_joint", daily, False, HORIZON),
            ("daily_joint_with_intercept", daily, True, HORIZON),
            ("direct_10d_joint", direct, True, 1),
            ("direct_10d_sensitivity", direct, False, 1),
        ):
            beta = (w @ fit["beta"])[["market", "rate"]]
            factor_loss = -100 * beta * shocks
            fitted_intercept = float(w @ fit["intercept"])
            drift_loss = -100 * fitted_intercept * intercept_days if add_intercept else 0.0
            predicted = float(factor_loss.sum() + drift_loss)
            rows.append({**common, "model": model, "predicted_loss_pct": predicted,
                         "underestimate_pp": actual - predicted, "absolute_error_pp": abs(actual - predicted),
                         "beta_market": float(beta.market), "beta_rate": float(beta.rate),
                         "contribution_market_pct": float(factor_loss.market),
                         "contribution_rate_pct": float(factor_loss.rate),
                         "contribution_intercept_pct": drift_loss,
                         "fitted_intercept": fitted_intercept,
                         "fit_return_horizon": 1 if model.startswith("daily") else HORIZON,
                         "paired_observations": fit["n"], "train_start": fit["train_start"],
                         "train_end": fit["train_end"], "standardized_design_condition": fit["condition"]})
        for model, predicted in (("spy_proxy", -100 * shocks.market), ("zero_loss", 0.0)):
            rows.append({**common, "model": model, "predicted_loss_pct": predicted,
                         "underestimate_pp": actual - predicted, "absolute_error_pp": abs(actual - predicted)})
    return pd.DataFrame(rows), direct["blocks"]


def run_replays(prices, factors, scenarios, portfolios):
    cases, rolling, training = [], [], []
    for scenario in scenarios:
        result, blocks = replay(prices, factors, scenario["reference"]["start"], scenario["reference"]["end"], portfolios)
        result.insert(0, "scenario", scenario["id"])
        cases.append(result)
        training.append(blocks)
    for pos in range(WINDOW + 1, len(prices) - HORIZON, HORIZON):
        result, blocks = replay(prices, factors, prices.index[pos], prices.index[pos + HORIZON], portfolios)
        rolling.append(result)
        training.append(blocks)
    if not rolling:
        raise ValueError("no full-window evaluation intervals")
    return pd.concat(cases, ignore_index=True), pd.concat(rolling, ignore_index=True), pd.concat(training, ignore_index=True).drop_duplicates()


def gates(summary):
    view = summary[summary.kind == "portfolio"].set_index(["subject", "model"])
    result = []
    for subject in view.index.get_level_values(0).unique():
        first, spy = view.loc[(subject, "daily_joint")], view.loc[(subject, "spy_proxy")]
        for model in CANDIDATES:
            candidate = view.loc[(subject, model)]
            checks = {
                "mae_better_than_first_revision": bool(candidate.mae_pp < first.mae_pp),
                "mae_better_than_spy": bool(candidate.mae_pp < spy.mae_pp),
                "tail_positive_underestimate_no_worse": bool(candidate.tail_mean_positive_underestimate_pp <= first.tail_mean_positive_underestimate_pp),
            }
            result.append({"subject": subject, "model": model, **checks, "passes_all_descriptive_gates": all(checks.values())})
    return pd.DataFrame(result)


def chart_config(summary):
    view = summary[summary.kind == "portfolio"].set_index(["subject", "model"])
    return {"id": "stress-validation-direct-10d", "title": "Stress 검증: 10일 직접 학습과 첫 수정 모델 비교",
            "height": 400, "description": "145개 이미 관측한 구간의 조건부 재현 MAE. 사후 관측한 충격을 입력했으며 새 홀드아웃 성능이 아님.",
            "spec": {"type": "bar", "x": "model", "y": ["변경 전", "TLT 30%"], "yLabel": "MAE (%p)",
                     "showValues": True, "valueFormat": {"style": "decimal", "maximumFractionDigits": 2}},
            "rows": [{"model": LABELS[m], "변경 전": float(view.loc[("before", m), "mae_pp"]),
                      "TLT 30%": float(view.loc[("after", m), "mae_pp"])}
                     for m in ("daily_joint", "direct_10d_joint", "direct_10d_sensitivity", "spy_proxy")]}


def write_report(cases, rolling, summary, checks, blocks):
    view = summary[summary.kind == "portfolio"].copy()
    view["label"] = view.model.map(LABELS)
    metrics = markdown_table(view, {"subject": "포트폴리오", "label": "모델", "mae_pp": "MAE %p",
        "tail_mae_pp": "손실 상위 15구간 MAE %p", "tail_mean_positive_underestimate_pp": "상위 15구간 양의 과소추정 평균 %p"})
    case_view = cases[(cases.kind == "portfolio") & cases.model.isin(["daily_joint", *CANDIDATES])].copy()
    case_view["label"] = case_view.model.map(LABELS)
    case_view["case_label"] = case_view.scenario.map(CASE_NAMES)
    case_table = markdown_table(case_view, {"case_label": "사례", "subject": "포트폴리오", "label": "모델",
        "predicted_loss_pct": "추정 손실 %", "actual_loss_pct": "실제 손실 %", "absolute_error_pp": "절대오차 %p"})
    passed = checks.groupby("model").passes_all_descriptive_gates.all()
    selected = [LABELS[m] for m in CANDIDATES if passed[m]]
    decision = "양쪽 포트폴리오에서 세 기술적 기준을 충족한 후보: " + ", ".join(selected) if selected else "양쪽 포트폴리오에서 세 기술적 기준을 모두 충족한 후보는 없습니다."
    recommendation = ("기준을 충족한 후보도 새 미사용 구간에서 확인해야 하며 이번 결과만으로 운영 모델을 교체하지 않습니다."
                      if selected else "이번 두 번째 수정 후보는 첫 수정 모델을 대체할 후보로 채택하지 않습니다. 주식+금리 일간 베타 모델을 기존의 추가 검증 우선 후보로 유지합니다.")
    regressions = []
    for (scenario, subject), group in case_view.groupby(["scenario", "subject"], sort=False):
        by_model = group.set_index("model")
        old = by_model.loc["daily_joint"]
        new = by_model.loc["direct_10d_joint"]
        if new.absolute_error_pp > old.absolute_error_pp:
            regressions.append(f"{CASE_NAMES[scenario]} / {subject}: {old.absolute_error_pp:.2f} → {new.absolute_error_pp:.2f}%p")
    train_counts = blocks.groupby("evaluation_start").used_in_fit.sum()
    by_summary = summary.set_index(["subject", "model"])
    observations = []
    for subject, label in (("before", "변경 전"), ("after", "TLT 편입 후")):
        first = by_summary.loc[(subject, "daily_joint")]
        direct = by_summary.loc[(subject, "direct_10d_joint")]
        no_alpha = by_summary.loc[(subject, "direct_10d_sensitivity")]
        observations.append(f"- {label}: 첫 수정 MAE {first.mae_pp:.2f}%p → 10일 직접 학습+절편 {direct.mae_pp:.2f}%p. 절편을 제외한 10일 민감도 모델은 {no_alpha.mae_pp:.2f}%p. 큰 손실 15구간의 양의 과소추정 평균은 {first.tail_mean_positive_underestimate_pp:.2f}%p → {direct.tail_mean_positive_underestimate_pp:.2f}%p.")
    gate_table = markdown_table(checks, {"subject": "포트폴리오", "model": "후보", "mae_better_than_first_revision": "첫 수정 MAE 개선",
        "mae_better_than_spy": "SPY MAE 개선", "tail_positive_underestimate_no_worse": "꼬리 과소추정 비악화", "passes_all_descriptive_gates": "세 기준 충족"})
    report = f"""# Stress 검증 두 번째 수정: 10거래일 수익률 직접 학습

**실험 구현·검증 완료. 운영 채택은 보류합니다.** {decision}
새 홀드아웃을 확보한 실험이 아니며, 첫 수정 이후 이미 확인한 동일 145개 구간에서 수행한 비교입니다.

{recommendation}

## 결과

{chr(10).join(observations)}

{metrics}

[평균 오차 차트](stress_validation_comparison.html) · [전체 자산·모델 요약](stress_validation_summary.csv) · [구간별 계산](stress_validation_rolling.csv)

## 변경한 계산

기존 일간 베타 × 10일 충격 근사와 비교하여, 10일 수정종가 수익률을 같은 10일 SPY 수익률과 금리 변화(bp)에 직접 회귀합니다.
28개 자산 각각의 공동추정 계수를 구하고 시작 비중으로 합산하므로 포트폴리오 실제 손실의 buy-and-hold 정의와 같은 학습 구간 수익률을 사용합니다.

- 기본 후보: `10일 자산 수익률 = 10일 절편 + 시장 베타 × SPY 10일 수익률 + 금리 베타 × 10일 금리 변화`.
- 기간 정렬 효과를 보기 위한 비교: 위에서 절편을 제외한 10일 민감도 모델.
- 절편 추가 효과를 보기 위한 비교: 첫 수정의 일간 베타에 `10 × 일간 절편`을 더한 모델. 일간 절편을 단순 누적한 진단용 근사이며 10일 직접 학습과 동일하지 않습니다.
- 단순 SPY와 0손실 기준을 함께 유지합니다. 모델·학습창·최소 표본·절편 포함/제외를 결과에 맞춰 튜닝하지 않았습니다.

## 학습 구간과 누수 방지

평가 시작일의 **전 거래일**을 마지막 종료일로 삼고 과거로 10거래일씩 이동해 학습 구간을 정합니다.
학습 구간의 시작·종료 날짜가 모두 평가 시작일보다 앞섭니다. 미래 수익률을 갖는 학습 행을 제거하지 않은 채 시작 날짜만 자르는 방식은 사용하지 않습니다.
각 회귀에는 겹치지 않는 학습 수익률만 넣고, 가장 오래된 10일 미만 잔여분은 버립니다. 입력 X 표준화와 절편은 해당 학습 자료 안에서만 추정합니다.

756일 창에서 가능한 학습 구간은 최대 75개입니다. 이 실험의 유효 표본 수는 사례·평가 구간을 합해 {int(train_counts.min())}~{int(train_counts.max())}개입니다.
2020년 사례는 약 2년 이력이므로 원래 블록 수가 54개입니다. 최소 유효 표본 {MIN_BLOCKS}개를 요구하며 부족하거나 상수/공선성으로 식별 불가하면 오류로 처리합니다.
금리의 학습 구간 시작 또는 종료 수준이 결측이면 해당 블록을 제외하고 보간하지 않습니다. 중간일 금리 결측은 양끝 수준이 있으면 변화량 계산을 방해하지 않습니다.
평가 충격은 기존과 같이 금리 수준의 과거 관측 이월 규칙을 사용하며, 그 값은 학습 표본 보충에 사용하지 않습니다.

[모든 학습 블록·사용 여부](stress_validation_training_blocks.csv) · [입력 해시·방법 manifest](stress_validation_manifest.json)

## 고정 위기 사례

{case_table}

10일 직접 학습+절편의 절대오차가 첫 수정보다 커진 사례: {'; '.join(regressions) if regressions else '없음'}.
2020년 주식·변동성 사례는 서로 겹칩니다. 평균 오차 개선과 위기 사례 개선을 구분하며 소수 사례를 독립 검증으로 세지 않습니다.
소수 고정 사례에서 오차가 줄더라도 전체 기간·큰 손실 구간의 성능이 악화하면 전반적인 개선으로 판단하지 않습니다.

## 판단 기준

두 예시 포트폴리오 각각에서 ① MAE가 첫 수정 모델보다 작고 ② 단순 SPY보다 작으며 ③ 큰 손실 15구간의 양의 과소추정 평균이 첫 수정 모델보다 커지지 않는지 확인합니다.
`mean(max(실제 손실−추정 손실, 0))`을 사용해 과대추정과 과소추정을 상쇄하지 않습니다. 15개 날짜는 포트폴리오별 실제 손실로 선정하고 모든 모델에 동일하게 적용합니다.

{gate_table}

기준 통과는 통계적 유의성·운영 승인·손실 보장을 뜻하지 않습니다. 학습 표본 감소와 구성 변화가 함께 발생하므로 차이를 순수한 기간 효과라고 단정하지 않습니다.
일간 베타에는 756일의 수익률이 있지만 직접 학습에는 약 75개 블록만 있습니다. 작은 표본의 계수 불안정성은 새 미사용 구간의 검증에서 확인해야 합니다.

## 해석 범위와 재현

사후 관측한 시장·금리 충격을 입력한 조건부 재현이며 충격 발생 자체의 예측이 아닙니다.
동시 금리의 인과 효과를 식별한 것도 아니며, 종목 고유 움직임·비선형성·미래 불확실성은 잔차로 남습니다.
고정 2026-10-23 수정종가 스냅샷, 현재 지원 28개 자산과 두 예시 포트폴리오 기준입니다. 당시 공표본·상장폐지 포함 검증이 아닙니다.
각 회귀의 10일 학습 수익률과 평가 수익률은 서로 겹치지 않지만, 서로 다른 평가 시점의 학습창은 겹칩니다. 결과 행을 독립 표본으로 합산하지 않습니다.

```bash
python -m analysis.portfolio_horizon_stress_experiment
python -m pytest tests/test_portfolio_horizon_stress_experiment.py
```

기존 원천·운영 엔진·첫 수정 결과는 보존합니다. 출력은 이 디렉터리에만 생성합니다.
표준 차트의 JSON 검증과 실제 화면 렌더링 검증은 구분하며, [검사 기록](stress_validation_checks.json)에 확인한 범위를 기록합니다.
"""
    (OUT / "stress_validation_report.md").write_text(report)


def main():
    paths = [ROOT / "data/portfolio" / n for n in ("prices.csv", "factors.csv", "scenarios.json", "snapshot_meta.json")]
    paths += [ROOT / "examples/portfolio" / f"{n}.json" for n in ("before", "after")]
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    prices, factors = (pd.read_csv(p, index_col="Date", parse_dates=True) for p in paths[:2])
    validate_inputs(prices, factors)
    cases, rolling, blocks = run_replays(prices, factors, json.loads(paths[2].read_text())["scenarios"], load_portfolios())
    summary = summarize(rolling)
    checks = gates(summary)
    OUT.mkdir(parents=True, exist_ok=True)
    for name, data in (("cases", cases), ("rolling", rolling), ("summary", summary), ("gates", checks), ("training_blocks", blocks)):
        data.to_csv(OUT / f"stress_validation_{name}.csv", index=False, float_format="%.12g")
    manifest = {"inputs_sha256": hashes,
        "runtime": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__},
        "method": {"training_horizon_observations": HORIZON, "training_window_daily_increments": WINDOW,
                   "minimum_usable_nonoverlap_blocks": MIN_BLOCKS, "training_anchor": "evaluation start minus one observation",
                   "training_complete_before_evaluation": True, "overlapping_training_returns_within_fit": False,
                   "evaluation_stride": HORIZON, "intercept_controls": True,
                   "parameter_tuning": False, "new_holdout": False, "production_adoption": False},
        "coverage": {"case_rows": len(cases), "rolling_rows": len(rolling), "summary_groups": len(summary),
                     "evaluation_intervals": int(summary.intervals.iloc[0]), "training_block_rows": len(blocks),
                     "min_usable_blocks": int(blocks.groupby('evaluation_start').used_in_fit.sum().min()),
                     "max_usable_blocks": int(blocks.groupby('evaluation_start').used_in_fit.sum().max())},
        "gates": ["MAE < first daily joint revision", "MAE < SPY proxy", "worst 15 loss windows positive-underestimate mean <= first revision", "both example portfolios"],
        "inputs_preserved": all(hashlib.sha256(p.read_bytes()).hexdigest() == hashes[str(p.relative_to(ROOT))] for p in paths)}
    (OUT / "stress_validation_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    (OUT / "stress_validation_comparison.json").write_text(json.dumps(chart_config(summary), indent=2, ensure_ascii=False) + "\n")
    write_report(cases, rolling, summary, checks, blocks)
    print(summary[summary.kind == "portfolio"].round(3).to_string(index=False))
    print(checks.to_string(index=False))


if __name__ == "__main__":
    main()
