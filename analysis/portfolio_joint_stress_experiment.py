"""Stress 검증 first revision: joint OLS betas times the same interval's joint shocks.

    python -m analysis.portfolio_joint_stress_experiment

Research only. Uses the frozen local snapshot and leaves production estimators,
scenarios, API, demo requests and the original Stress 검증 results intact.
"""

import hashlib
import json
import platform
from pathlib import Path

import numpy as np
import pandas as pd

from analysis.portfolio_stress_validation import (
    CASE_NAMES, HORIZON, MIN_OBSERVATIONS, WINDOW, load_portfolios,
    markdown_table, realized_shock, subject_weights, validate_inputs,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "portfolio" / "joint_stress"
FACTORS = ("market", "rate", "volatility")
MODEL_FACTORS = {
    "legacy_market": ("market",),
    "legacy_rate": ("rate",),
    "legacy_volatility": ("volatility",),
    "matched_market": ("market",),
    "joint_market_rate": ("market", "rate"),
    "joint_market_rate_vix": FACTORS,
}
MODEL_LABELS = {
    "legacy_market": "기존 시장 단일팩터", "legacy_rate": "기존 금리 단일팩터",
    "legacy_volatility": "기존 VIX 단일팩터", "matched_market": "동일 표본 시장 단일팩터",
    "joint_market_rate": "주식+금리 OLS", "joint_market_rate_vix": "주식+금리+VIX OLS",
    "spy_proxy": "단순 SPY", "zero_loss": "0손실 기준",
}
CANDIDATES = ("joint_market_rate", "joint_market_rate_vix")


def fit_ols(x, y, min_observations=MIN_OBSERVATIONS):
    """Fit all asset columns together; scale X using training observations only.

    An intercept is fitted, then omitted from the stress return exactly as in
    the existing daily beta-times-shock approximation. No causal interpretation.
    """
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if x.ndim != 2 or y.ndim != 2 or x.shape[0] != y.shape[0]:
        raise ValueError("X and Y must be aligned two-dimensional matrices")
    if len(x) < min_observations or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("insufficient or nonfinite complete-case training data")
    center, scale = x.mean(axis=0), x.std(axis=0)
    if (scale <= 0).any():
        raise ValueError("constant factor cannot identify a beta")
    design = np.column_stack([np.ones(len(x)), (x - center) / scale])
    params, _, rank, singular_values = np.linalg.lstsq(design, y, rcond=None)
    if rank != design.shape[1]:
        raise ValueError("rank-deficient joint design; no silent fallback")
    beta = params[1:] / scale[:, None]
    intercept = params[0] - center @ beta
    return beta, intercept, len(x), float(singular_values[0] / singular_values[-1])


def fit_before(prices, factors, start, window=WINDOW):
    """Every fitted value uses only the window strictly before start's close."""
    pos = prices.index.get_loc(pd.Timestamp(start))
    train_prices = prices.iloc[max(0, pos - window - 1):pos]
    if len(train_prices) - 1 < MIN_OBSERVATIONS:
        raise ValueError("not enough pre-start returns")
    returns = train_prices.pct_change(fill_method=None).iloc[1:]
    train_factors = factors.loc[train_prices.index]
    moves = pd.DataFrame({
        "market": returns["SPY"],
        "rate": train_factors["DGS10"].diff().iloc[1:] * 100,
        "volatility": train_factors["VIX"].diff().iloc[1:],
    }, index=returns.index)
    complete = moves.notna().all(axis=1) & returns.notna().all(axis=1)
    models = {}
    for model, selected in MODEL_FACTORS.items():
        # A matched single-factor model isolates extra-factor vs sample changes.
        mask = complete if model == "matched_market" or model in CANDIDATES else moves[list(selected)].notna().all(axis=1)
        beta, intercept, n, condition = fit_ols(moves.loc[mask, list(selected)], returns.loc[mask])
        full_beta = pd.DataFrame(0.0, index=prices.columns, columns=FACTORS)
        full_beta.loc[:, list(selected)] = beta.T
        models[model] = {
            "beta": full_beta, "intercept": pd.Series(intercept, index=prices.columns),
            "n": n, "condition": condition,
            "train_start": returns.index[0].date().isoformat(),
            "train_end": returns.index[-1].date().isoformat(),
            "training_returns": len(returns),
        }
    return models


def replay(prices, factors, start, end, portfolios):
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    if prices.index.get_loc(end) - prices.index.get_loc(start) != HORIZON:
        raise ValueError("expected exactly 10 trading observations")
    fitted = fit_before(prices, factors, start)
    shocks = pd.Series({f: realized_shock(prices, factors, start, end, f) for f in FACTORS})
    actual_returns = prices.loc[end] / prices.loc[start] - 1
    rows = []
    for subject, weights in subject_weights(prices, portfolios).items():
        w = pd.Series(weights).reindex(prices.columns, fill_value=0.0)
        actual = -100 * float(w @ actual_returns)
        common = {
            "subject": subject, "kind": "portfolio" if subject in portfolios else "asset",
            "start": str(start.date()), "end": str(end.date()), "actual_loss_pct": actual,
            **{f"shock_{f}": float(shocks[f]) for f in FACTORS},
        }
        for model, fit in fitted.items():
            # Joint coefficients are estimated together; legacy marginal betas
            # are never summed. Each contribution is expressed as a loss in %.
            beta = w @ fit["beta"]
            contributions = -100 * beta * shocks
            predicted = float(contributions.sum())
            rows.append({
                **common, "model": model, "predicted_loss_pct": predicted,
                "underestimate_pp": actual - predicted, "absolute_error_pp": abs(actual - predicted),
                **{f"beta_{f}": float(beta[f]) for f in FACTORS},
                **{f"contribution_{f}_pct": float(contributions[f]) for f in FACTORS},
                "fitted_daily_intercept": float(w @ fit["intercept"]),
                "paired_observations": fit["n"], "training_returns": fit["training_returns"],
                "full_window": fit["training_returns"] == WINDOW,
                "train_start": fit["train_start"], "train_end": fit["train_end"],
                "standardized_design_condition": fit["condition"],
            })
        for model, predicted in (("spy_proxy", -100 * shocks["market"]), ("zero_loss", 0.0)):
            rows.append({**common, "model": model, "predicted_loss_pct": predicted,
                         "underestimate_pp": actual - predicted, "absolute_error_pp": abs(actual - predicted)})
    return pd.DataFrame(rows)


def run_replays(prices, factors, portfolios, scenarios):
    cases, rolling = [], []
    for scenario in scenarios:
        frame = replay(prices, factors, scenario["reference"]["start"], scenario["reference"]["end"], portfolios)
        frame.insert(0, "scenario", scenario["id"])
        cases.append(frame)
    for pos in range(WINDOW + 1, len(prices) - HORIZON, HORIZON):
        rolling.append(replay(prices, factors, prices.index[pos], prices.index[pos + HORIZON], portfolios))
    if not rolling:
        raise ValueError("no complete validation intervals")
    return pd.concat(cases, ignore_index=True), pd.concat(rolling, ignore_index=True)


def summarize(rows):
    result = []
    for (subject, kind, model), group in rows.groupby(["subject", "kind", "model"], sort=False):
        tail = group.nlargest(int(np.ceil(len(group) * 0.1)), "actual_loss_pct")
        result.append({
            "subject": subject, "kind": kind, "model": model, "intervals": len(group),
            "mae_pp": group["absolute_error_pp"].mean(),
            "rmse_pp": np.sqrt((group["underestimate_pp"] ** 2).mean()),
            "mean_underestimate_pp": group["underestimate_pp"].mean(),
            "tail_intervals": len(tail), "tail_mae_pp": tail["absolute_error_pp"].mean(),
            "tail_mean_underestimate_pp": tail["underestimate_pp"].mean(),
            "tail_mean_positive_underestimate_pp": tail["underestimate_pp"].clip(lower=0).mean(),
        })
    return pd.DataFrame(result)


def adoption_checks(summary):
    """Fixed descriptive gates; passing is not permission to deploy or tune."""
    s = summary[summary["kind"] == "portfolio"].set_index(["subject", "model"])
    rows = []
    for subject in s.index.get_level_values(0).unique():
        old, spy = s.loc[(subject, "legacy_market")], s.loc[(subject, "spy_proxy")]
        for model in CANDIDATES:
            candidate = s.loc[(subject, model)]
            mae_old = bool(candidate.mae_pp < old.mae_pp)
            mae_spy = bool(candidate.mae_pp < spy.mae_pp)
            tail = bool(candidate.tail_mean_positive_underestimate_pp <= old.tail_mean_positive_underestimate_pp)
            rows.append({"subject": subject, "model": model,
                         "mae_better_than_legacy_market": mae_old,
                         "mae_better_than_spy": mae_spy,
                         "tail_positive_underestimate_no_worse_than_legacy": tail,
                         "passes_all_descriptive_gates": mae_old and mae_spy and tail})
    return pd.DataFrame(rows)


def chart_config(summary):
    chosen = summary[(summary.kind == "portfolio") & summary.model.isin(
        ["legacy_market", "joint_market_rate", "joint_market_rate_vix", "spy_proxy"])]
    rows = []
    for model in ("legacy_market", "joint_market_rate", "joint_market_rate_vix", "spy_proxy"):
        values = chosen[chosen.model == model].set_index("subject")
        rows.append({"model": MODEL_LABELS[model], "변경 전": float(values.at["before", "mae_pp"]),
                     "TLT 30%": float(values.at["after", "mae_pp"])})
    return {"id": "stress-validation-joint-comparison", "title": "145개 구간: 동시 충격 모델의 평균 절대오차",
            "height": 380, "description": "낮을수록 실제 총손실에 가까움. 사후 관측 충격을 넣은 조건부 비교이며 새 홀드아웃 성능이 아님.",
            "spec": {"type": "bar", "x": "model", "y": ["변경 전", "TLT 30%"], "yLabel": "MAE (%p)",
                     "showValues": True, "valueFormat": {"style": "decimal", "maximumFractionDigits": 2}},
            "rows": rows}


def write_report(cases, rolling, summary, gates):
    view = summary[summary.kind == "portfolio"].copy()
    view["model_label"] = view.model.map(MODEL_LABELS)
    metrics = markdown_table(view, {"subject": "포트폴리오", "model_label": "모델",
        "mae_pp": "MAE %p", "tail_mae_pp": "손실 상위 15구간 MAE %p",
        "tail_mean_positive_underestimate_pp": "상위 15구간 양의 과소추정 평균 %p"})
    event = cases[(cases.kind == "portfolio") & cases.model.isin(
        ["legacy_market", "joint_market_rate", "joint_market_rate_vix", "spy_proxy"])].copy()
    event["case_label"] = event.scenario.map(CASE_NAMES)
    event["model_label"] = event.model.map(MODEL_LABELS)
    event_table = markdown_table(event, {"case_label": "사례", "subject": "포트폴리오",
        "model_label": "모델", "predicted_loss_pct": "추정 손실 %", "actual_loss_pct": "실제 손실 %"})
    gate_table = markdown_table(gates, {"subject": "포트폴리오", "model": "후보",
        "mae_better_than_legacy_market": "기존 시장 MAE 개선",
        "mae_better_than_spy": "SPY MAE 개선",
        "tail_positive_underestimate_no_worse_than_legacy": "꼬리 과소추정 비악화",
        "passes_all_descriptive_gates": "세 기준 충족"})
    ready = gates.groupby("model").passes_all_descriptive_gates.all()
    candidates = [MODEL_LABELS[m] for m in CANDIDATES if ready[m]]
    conclusion = ("양쪽 예시 포트폴리오에서 세 비교 기준을 충족한 후보: " + ", ".join(candidates)
                  if candidates else "양쪽 예시 포트폴리오에서 세 비교 기준을 모두 충족한 후보는 없습니다.")
    indexed = summary.set_index(["subject", "model"])
    observations = []
    for subject, label in (("before", "변경 전"), ("after", "TLT 30% 편입 후")):
        old = indexed.loc[(subject, "legacy_market")]
        joint = indexed.loc[(subject, "joint_market_rate")]
        three = indexed.loc[(subject, "joint_market_rate_vix")]
        spy = indexed.loc[(subject, "spy_proxy")]
        observations.append(
            f"- {label}: 시장 단일팩터 MAE {old.mae_pp:.2f}%p → 주식+금리 {joint.mae_pp:.2f}%p. "
            f"단순 SPY {spy.mae_pp:.2f}%p, VIX까지 추가 {three.mae_pp:.2f}%p. "
            f"주식+금리의 상위 15구간 양의 과소추정 평균은 {old.tail_mean_positive_underestimate_pp:.2f}%p → {joint.tail_mean_positive_underestimate_pp:.2f}%p."
        )
    regressions = []
    for (scenario, subject), group in cases[cases.kind == "portfolio"].groupby(["scenario", "subject"], sort=False):
        model_rows = group.set_index("model")
        old, new = model_rows.loc["legacy_market"], model_rows.loc["joint_market_rate"]
        if new.absolute_error_pp > old.absolute_error_pp:
            regressions.append(f"{CASE_NAMES[scenario]} / {subject}: {old.absolute_error_pp:.2f} → {new.absolute_error_pp:.2f}%p")
    regression_text = "; ".join(regressions) if regressions else "고정 세 사례의 두 포트폴리오에서 악화 없음"
    asset_base = summary[(summary.kind == "asset") & (summary.model == "legacy_market")].set_index("subject")
    asset_joint = summary[(summary.kind == "asset") & (summary.model == "joint_market_rate")].set_index("subject")
    asset_improvements = int((asset_joint.mae_pp < asset_base.mae_pp).sum())
    prefer_two = all(
        indexed.loc[(subject, "joint_market_rate"), "mae_pp"] <= indexed.loc[(subject, "joint_market_rate_vix"), "mae_pp"]
        and indexed.loc[(subject, "joint_market_rate"), "tail_mean_positive_underestimate_pp"] <= indexed.loc[(subject, "joint_market_rate_vix"), "tail_mean_positive_underestimate_pp"]
        for subject in ("before", "after")
    )
    recommendation = ("추가 검증의 우선 후보는 **주식+금리 2팩터 OLS**입니다. 두 예시 포트폴리오에서 VIX까지 추가한 모델보다 MAE와 꼬리 구간 양의 과소추정 평균이 작거나 같았고, 팩터 수가 적습니다. 이는 현재 표본의 비교 판단이며 우월성 확정이나 운영 승인을 뜻하지 않습니다."
                      if prefer_two else "추가 검증 후보는 표의 평균 오차와 꼬리 오차를 함께 보고 판단해야 합니다. 현재 비교에서 한 후보의 일관된 우위를 주장하지 않습니다.")
    (OUT / "experiment.md").write_text(f"""# Stress 검증 첫 수정: 다중회귀와 당시 동시 충격

**실험 구현·검증 완료. 운영 채택 판단은 보류합니다.** {conclusion}
기존 145개 구간을 이미 검토한 뒤 설계한 실험이므로 독립적인 새 홀드아웃 검증으로 해석하지 않습니다.

## 핵심 결과와 남은 문제

{chr(10).join(observations)}
- 현재 지원 자산 {len(asset_base)}개 중 {asset_improvements}개에서 주식+금리 모델의 MAE가 기존 시장 단일팩터보다 작았습니다. 현재 자산군 내 비교이며 모집단·유의성 추정이 아닙니다.
- 주식+금리 대비 VIX 추가의 가치는 표의 평균·꼬리 오차로 판단합니다. 모델 복잡도 증가 자체를 개선으로 보지 않습니다.
- **고정 위기 사례에서 악화한 경우도 남았습니다.** 주식+금리 모델의 절대오차 증가: {regression_text}. 평균 구간의 개선을 모든 위기 재현의 개선으로 해석할 수 없습니다.

이 결과로 새 데이터에서 우선 확인할 후보를 좁힐 수 있지만 운영 엔진을 자동 교체하지 않습니다. 기존 단일팩터 시나리오는 개별 민감도로 유지하고, 동시 충격 실험을 실제 금리만의 인과 효과로 표시하지 않습니다.

{recommendation}

## 수정 내용

- 일간 수익률·최대 756일 학습창·10거래일 평가를 유지하고, 주식+금리 / 주식+금리+VIX의 계수를 **동시에 OLS로 추정**했습니다.
- 동일 구간의 SPY 수익률, DGS10 변화(bp), VIX 변화(pt)를 함께 입력해 계수와 곱합니다. 함께 추정한 계수의 기여도만 합산하며 기존 단변량 베타는 합산하지 않습니다.
- 기존 시장·금리·VIX 단일팩터, 단순 SPY, 0손실과 비교합니다. 추가로 다중회귀와 같은 완전 관측일만 쓴 시장 단일팩터를 두어 금리 결측에 따른 표본 변화 효과를 분리했습니다.
- 모델·기간·포트폴리오 비중·선택 기준은 결과에 맞춰 조정하지 않았습니다. 이번 단계에는 Ridge, 가중치 튜닝, 10일 직접 학습을 추가하지 않았습니다.

## 145개 비중첩 구간 결과

기간 {rolling.start.min()}~{rolling.end.max()}. 양수 손실·음수 이익입니다.
손실 상위 약 10%인 15구간은 포트폴리오별 실제 손실 순위로 사후 고정하며, 모든 모델에 같은 날짜를 적용합니다.
양의 과소추정 평균은 `mean(max(실제 손실−추정 손실, 0))`로, 과대추정과 상쇄하지 않는 오차입니다.

{metrics}

[평균 오차 차트](comparison.html) · [전체 자산·모델 요약](summary.csv) · [모든 구간의 추정·실제·팩터 기여도](rolling.csv)

## 비교 기준과 판단

실험의 기술적 기준은 두 포트폴리오 **각각**에서 ① MAE가 기존 시장 모델보다 작고 ② 단순 SPY보다 작으며 ③ 상위 15구간의 양의 과소추정 평균이 기존 시장 모델보다 커지지 않는 것입니다.
이 기준은 통계적 유의성 검정이나 위험 허용 한도가 아닙니다. 통과해도 새 미사용 기간의 검증이 필요합니다.

{gate_table}

## 기존 세 충격 구간

{event_table}

[전체 사례 결과](cases.csv)에 기존 금리·VIX 단일팩터도 보존했습니다.
금리 구간의 단일팩터 오차 개선과, 전체 구간에서 기존 시장 모델 대비 개선은 별개의 비교입니다.
주식·변동성의 2020년 사례는 서로 겹치며 학습 이력은 각각 544/542개 일간 수익률로 756개보다 짧습니다.

## 계산과 한계

학습 종료일은 구간 시작일 전 거래일입니다. 모델별 X·Y에서 결측을 제외하며 금리 변화는 과거·당일 금리 수준이 모두 있는 날만 사용합니다.
다중회귀와 동일 표본 기준은 세 입력이 모두 있는 날을 사용합니다. 252개 미만 유효 표본, 상수 팩터, 완전 공선성은 조용히 0으로 바꾸지 않고 오류로 처리합니다.
학습 자료 안에서만 X를 표준화하고, 원래 단위의 베타로 환산합니다. 원단위 계수와 표준화 설계행렬의 조건수를 CSV에 남겼습니다.

추정 손실 = `−100 × Σ_f(Σ_i 시작비중_i × 공동추정 베타_if) × 관측 10일 팩터충격_f`.
회귀 절편은 추정하되 기존 스트레스 근사와 같이 손실 계산에 더하지 않습니다.
실제 손실 = `−100 × Σ_i 시작비중_i × (종료 수정종가_i / 시작 수정종가_i − 1)`이며 구간 내 매매 없는 buy-and-hold입니다.
일간 베타와 10일 충격의 선형 근사, 구간 중 비중 변화, 비선형성과 종목 고유 잔차는 여전히 남습니다.
공동추정 계수는 조건부 연관이며 금리의 인과 효과를 식별한 것으로 해석하지 않습니다.

입력은 고정 2026-10-23 스냅샷과 현재 28개 자산군·두 예시 포트폴리오입니다. 당시 공표본 재현이나 상장폐지 종목 포함 검증은 아닙니다.
충격과 극단 사례는 사후 관측값입니다. 시장 급락을 미리 예측하는 모델이 아니며 미래 총손실을 보장하지 않습니다.
10일 평가 수익률은 겹치지 않지만 학습창은 겹칩니다. 개별 자산·모델 행을 독립 위기 표본으로 세지 않습니다.

## 재현

```bash
python -m analysis.portfolio_joint_stress_experiment
python -m pytest tests/test_portfolio_joint_stress_experiment.py
```

[입력 해시·방법 manifest](manifest.json)에 실행 환경, 평가 구간과 비교 기준을 기록했습니다.
표준 차트는 `comparison.json`을 Data 렌더러에 전달해 별도 생성합니다. 브라우저가 없는 실행환경에서는 픽셀·상호작용 검증을 주장하지 않습니다.
실행한 테스트·독립 계산·보존 확인은 [검사 기록](checks.json)에 남겼습니다.
""")


def main():
    paths = [ROOT / "data/portfolio" / n for n in ("prices.csv", "factors.csv", "scenarios.json", "snapshot_meta.json")]
    paths += [ROOT / "examples/portfolio" / f"{n}.json" for n in ("before", "after")]
    inputs = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    prices = pd.read_csv(paths[0], index_col="Date", parse_dates=True)
    factors = pd.read_csv(paths[1], index_col="Date", parse_dates=True)
    validate_inputs(prices, factors)
    cases, rolling = run_replays(prices, factors, load_portfolios(), json.loads(paths[2].read_text())["scenarios"])
    summary = summarize(rolling)
    gates = adoption_checks(summary)
    OUT.mkdir(parents=True, exist_ok=True)
    for name, frame in (("cases", cases), ("rolling", rolling), ("summary", summary), ("gates", gates)):
        frame.to_csv(OUT / f"{name}.csv", index=False, float_format="%.12g")
    manifest = {"inputs_sha256": inputs,
        "runtime": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__},
        "models": {k: list(v) for k, v in MODEL_FACTORS.items()},
        "method": {"window_daily_returns": WINDOW, "minimum_complete_returns": MIN_OBSERVATIONS,
                   "train_cutoff": "strictly before start", "horizon": HORIZON, "stride": HORIZON,
                   "shock_input": "joint realized interval changes; conditional replay, not forecast",
                   "intercept": "fitted, excluded from stress return", "parameter_tuning": False,
                   "new_holdout": False, "production_adoption": False},
        "coverage": {"case_rows": len(cases), "rolling_rows": len(rolling), "summary_rows": len(summary),
                     "intervals": int(summary.intervals.iloc[0]), "assets": len(prices.columns), "portfolios": 2},
        "descriptive_gates": ["MAE < legacy_market", "MAE < spy_proxy",
                              "worst-decile mean positive underestimate <= legacy_market", "both demo portfolios must pass"],
        "source_preserved": all(hashlib.sha256(p.read_bytes()).hexdigest() == inputs[str(p.relative_to(ROOT))] for p in paths)}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    (OUT / "comparison.json").write_text(json.dumps(chart_config(summary), indent=2, ensure_ascii=False) + "\n")
    write_report(cases, rolling, summary, gates)
    print(summary[summary.kind == "portfolio"].round(3).to_string(index=False))
    print(gates.to_string(index=False))


if __name__ == "__main__":
    main()
