"""Stress 검증: retrospective equity/rate situation diagnostics, no refitting.

    python -m analysis.portfolio_regime_stress_diagnostics
"""

import hashlib
import itertools
import json
import platform
from pathlib import Path

import numpy as np
import pandas as pd

from analysis.portfolio_stress_validation import markdown_table

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/portfolio/regime_stress"
SOURCE = ROOT / "reports/portfolio/joint_stress/rolling.csv"
FOCAL = "joint_market_rate"
MODELS = (FOCAL, "legacy_market", "joint_market_rate_vix", "spy_proxy")
EQUITY_CUTOFF = -0.05
RATE_CUTOFF = 20.0
SMALL_SAMPLE = 5
TOLERANCE = 1e-9
REGIMES = ("joint_shock", "equity_down", "rate_up", "neither")
LABELS = {
    "joint_shock": "주식 급락·금리 급등 동반",
    "equity_down": "주식 급락(금리 기준 미충족)",
    "rate_up": "금리 급등(주식 기준 미충족)",
    "neither": "두 기준 모두 미충족",
}
MODEL_LABELS = {FOCAL: "첫 수정: 주식+금리", "legacy_market": "기존 시장 단일팩터",
                "joint_market_rate_vix": "주식+금리+VIX", "spy_proxy": "단순 SPY"}
MARKET_BINS = ("selloff", "down", "flat", "up", "rally")
RATE_BINS = ("rate_down", "rate_middle", "rate_up")
MARKET_LABELS = {"selloff": "SPY ≤−5%", "down": "SPY (−5%,−2%]", "flat": "SPY (−2%,+2%)",
                 "up": "SPY [+2%,+5%)", "rally": "SPY ≥+5%"}
RATE_LABELS = {"rate_down": "금리 ≤−20bp", "rate_middle": "금리 (−20,+20)bp", "rate_up": "금리 ≥+20bp"}


def classify(market, rate, equity_cutoff=EQUITY_CUTOFF, rate_cutoff=RATE_CUTOFF):
    market, rate = np.asarray(market, dtype=float), np.asarray(rate, dtype=float)
    if market.shape != rate.shape or not np.isfinite(market).all() or not np.isfinite(rate).all():
        raise ValueError("finite, aligned realized shocks are required")
    if equity_cutoff >= 0 or rate_cutoff <= 0:
        raise ValueError("equity cutoff must be negative and rate cutoff positive")
    down, up = market <= equity_cutoff, rate >= rate_cutoff
    return np.select([down & up, down, up], REGIMES[:3], default="neither")


def prepare_rows(raw):
    needed = ["subject", "kind", "start", "end", "model", "actual_loss_pct", "predicted_loss_pct",
              "shock_market", "shock_rate", "shock_volatility"]
    if raw[needed].isna().any().any() or raw.duplicated(["subject", "model", "start", "end"]).any():
        raise ValueError("missing required data or duplicate prediction keys")
    numeric = needed[5:]
    if not np.isfinite(raw[numeric].to_numpy()).all():
        raise ValueError("nonfinite losses or shocks")
    for field in ("shock_market", "shock_rate", "shock_volatility"):
        if raw.groupby(["start", "end"])[field].nunique().ne(1).any():
            raise ValueError("shocks differ across models or subjects on the same interval")
    if raw.groupby(["subject", "start", "end"]).actual_loss_pct.nunique().ne(1).any():
        raise ValueError("actual loss differs across models")
    intervals = raw[["start", "end", "shock_market", "shock_rate", "shock_volatility"]].drop_duplicates().sort_values("start").reset_index(drop=True)
    if intervals.duplicated("start").any():
        raise ValueError("more than one end date per start")
    for i, row in intervals.iterrows():
        if row.start >= row.end or (i and row.start < intervals.iloc[i - 1].end):
            raise ValueError("outcome intervals must be ordered and non-overlapping")
    intervals["regime"] = classify(intervals.shock_market, intervals.shock_rate)
    intervals["market_bin"] = np.select(
        [intervals.shock_market <= -0.05, intervals.shock_market <= -0.02,
         intervals.shock_market < 0.02, intervals.shock_market < 0.05], MARKET_BINS[:-1], default="rally")
    intervals["rate_bin"] = np.select([intervals.shock_rate <= -20, intervals.shock_rate < 20], RATE_BINS[:-1], default="rate_up")
    intervals["cross_regime"] = intervals.market_bin + "__" + intervals.rate_bin
    intervals["period"] = np.where(intervals.index < len(intervals) // 2, "early", "late")
    selected = raw[raw.model.isin(MODELS)][needed].copy()
    expected = set(map(tuple, intervals[["start", "end"]].to_numpy()))
    for _, group in selected.groupby(["subject", "model"]):
        if set(map(tuple, group[["start", "end"]].to_numpy())) != expected:
            raise ValueError("models or subjects do not share exactly the same intervals")
    if selected.groupby("subject").model.nunique().ne(len(MODELS)).any():
        raise ValueError("required comparator model missing")
    selected = selected.merge(intervals[["start", "end", "regime", "cross_regime", "period"]],
                              on=["start", "end"], validate="many_to_one")
    selected["underestimate_pp"] = selected.actual_loss_pct - selected.predicted_loss_pct
    selected["absolute_error_pp"] = selected.underestimate_pp.abs()
    return selected, intervals


def metrics(group, total_n, total_abs):
    n = len(group)
    losses = group[group.actual_loss_pct > TOLERANCE]
    gains = group[group.actual_loss_pct < -TOLERANCE]
    error = group.underestimate_pp
    return {
        "n": n, "small_sample": n < SMALL_SAMPLE,
        "mae_pp": group.absolute_error_pp.mean(), "median_absolute_error_pp": group.absolute_error_pp.median(),
        "rmse_pp": np.sqrt((error ** 2).mean()), "mean_signed_error_pp": error.mean(),
        "under_count": int((error > TOLERANCE).sum()), "over_count": int((error < -TOLERANCE).sum()),
        "under_fraction_all": (error > TOLERANCE).mean() if n else np.nan,
        "mean_positive_underestimate_pp": error.clip(lower=0).mean(),
        "actual_loss_n": len(losses),
        "actual_loss_mean_signed_error_pp": losses.underestimate_pp.mean(),
        "actual_gain_n": len(gains), "actual_gain_mean_signed_error_pp": gains.underestimate_pp.mean(),
        "actual_loss_under_fraction": (losses.underestimate_pp > TOLERANCE).mean() if len(losses) else np.nan,
        "actual_loss_mean_positive_underestimate_pp": losses.underestimate_pp.clip(lower=0).mean(),
        "predicted_gain_actual_loss_count": int((losses.predicted_loss_pct < -TOLERANCE).sum()),
        "large_error_count": int((group.absolute_error_pp >= 5).sum()),
        "total_absolute_error_pp": group.absolute_error_pp.sum(),
        "error_share": group.absolute_error_pp.sum() / total_abs if total_abs > TOLERANCE else np.nan,
        "observation_share": n / total_n if total_n else np.nan,
    }


def summarize(rows, dimension, levels):
    result = []
    for (subject, kind, model), data in rows.groupby(["subject", "kind", "model"], sort=False):
        for level in levels:
            group = data[data[dimension] == level]
            result.append({"subject": subject, "kind": kind, "model": model, dimension: level,
                           **metrics(group, len(data), data.absolute_error_pp.sum())})
    return pd.DataFrame(result)


def period_summary(rows):
    result = []
    for period in ("early", "late"):
        frame = summarize(rows[rows.period == period], "regime", REGIMES)
        frame.insert(0, "period", period)
        result.append(frame)
    return pd.concat(result, ignore_index=True)


def threshold_sensitivity(rows):
    portfolios = rows[(rows.kind == "portfolio") & (rows.model == FOCAL)].copy()
    result = []
    for equity, rate in itertools.product((-0.03, -0.05, -0.07), (10.0, 20.0, 30.0)):
        portfolios["regime"] = classify(portfolios.shock_market, portfolios.shock_rate, equity, rate)
        frame = summarize(portfolios, "regime", REGIMES)
        frame.insert(0, "equity_cutoff", equity)
        frame.insert(1, "rate_cutoff_bp", rate)
        result.append(frame)
    return pd.concat(result, ignore_index=True)


def chart_config(summary, metric, title):
    chosen = summary[(summary.kind == "portfolio") & (summary.model == FOCAL)].set_index(["subject", "regime"])
    rows = []
    for regime in REGIMES:
        before, after = chosen.loc[("before", regime)], chosen.loc[("after", regime)]
        rows.append({"regime": f"{LABELS[regime]} (n={int(before.n)})",
                     "변경 전": float(before[metric]) if before.n else None,
                     "TLT 30%": float(after[metric]) if after.n else None})
    return {"id": "stress-validation-regime-" + metric.replace("_", "-"), "title": title, "height": 410,
            "description": "첫 수정 모델, 사후 관측 충격별 분류. n<5는 작은 표본. N/A는 해당 구간 없음. 양의 편향=실제가 추정보다 손실 쪽.",
            "spec": {"type": "bar", "x": "regime", "y": ["변경 전", "TLT 30%"], "yLabel": "%p",
                     "showValues": True, "valueFormat": {"style": "decimal", "maximumFractionDigits": 2}}, "rows": rows}


def format_table(frame, columns):
    return markdown_table(frame, columns).replace("nan", "N/A")


def write_report(summary, periods, sensitivity, worst, intervals, cross):
    focal = summary[(summary.kind == "portfolio") & (summary.model == FOCAL)].copy()
    focal["label"] = focal.regime.map(LABELS)
    focal["direction"] = np.where(focal.n == 0, "N/A", np.where(focal.mean_signed_error_pp > TOLERANCE, "실제가 더 손실 쪽", np.where(focal.mean_signed_error_pp < -TOLERANCE, "추정이 더 손실 쪽", "차이 없음")))
    focal["error_share_pct"] = focal.error_share * 100
    table = format_table(focal, {"subject": "포트폴리오", "label": "상황", "n": "구간 수", "mae_pp": "MAE %p",
        "mean_signed_error_pp": "평균 실제−추정 %p", "actual_loss_n": "실제 손실 구간 수",
        "actual_loss_mean_positive_underestimate_pp": "실제 손실 구간의 양의 과소추정 평균 %p",
        "error_share_pct": "전체 절대오차 기여 %", "small_sample": "n<5"})
    outcome_table = format_table(focal, {"subject": "포트폴리오", "label": "상황",
        "actual_loss_n": "실제 손실 n", "actual_loss_mean_signed_error_pp": "손실 구간 실제−추정 %p",
        "actual_gain_n": "실제 이익 n", "actual_gain_mean_signed_error_pp": "이익 구간 실제−추정 %p"})
    observations = []
    regime_counts = intervals.regime.value_counts()
    observations.append(f"- 주식 급락 표본은 동반 충격 {int(regime_counts.get('joint_shock', 0))}개, 금리 급등 기준 미충족 {int(regime_counts.get('equity_down', 0))}개 구간입니다. 극단 충격에서 일정한 보정 방향을 추정하기에는 부족합니다.")
    cross_view = cross[(cross.kind == "portfolio") & (cross.model == FOCAL)].copy()
    cross_view["label"] = cross_view.cross_regime.map(lambda key: " / ".join([MARKET_LABELS[key.split('__')[0]], RATE_LABELS[key.split('__')[1]]]))
    for subject, group in focal.groupby("subject", sort=False):
        remainder = group[group.regime == "neither"].iloc[0]
        observations.append(f"- {subject}: 두 기준 모두 미충족인 {int(remainder.n)}개 구간은 전체 관측의 {100*remainder.observation_share:.1f}%, 전체 절대오차의 {remainder.error_share_pct:.1f}%입니다. 오차의 대부분이지만 표본 자체도 대부분이므로 이 상황만의 특수한 실패라고 단정하지 않습니다.")
        eligible = cross_view[(cross_view.subject == subject) & (cross_view.n >= SMALL_SAMPLE)]
        if not eligible.empty:
            largest = eligible.loc[eligible.mae_pp.idxmax()]
            observations.append(f"- {subject}: 세부 15개 셀 중 n≥{SMALL_SAMPLE}인 곳에서 MAE가 가장 큰 상황은 **{largest['label']}**이며 {largest.mae_pp:.2f}%p, n={int(largest.n)}입니다. 표본 안에서 사후 선택한 관측이며 새 경보·모델 선택 규칙이 아닙니다.")
    repeat_rows = []
    for (subject, regime), group in periods[(periods.kind == "portfolio") & (periods.model == FOCAL)].groupby(["subject", "regime"], sort=False):
        indexed = group.set_index("period")
        early, late = indexed.loc["early"], indexed.loc["late"]
        sufficient = early.n >= SMALL_SAMPLE and late.n >= SMALL_SAMPLE
        same_sign = bool(sufficient and np.sign(early.mean_signed_error_pp) == np.sign(late.mean_signed_error_pp) and abs(early.mean_signed_error_pp) > TOLERANCE and abs(late.mean_signed_error_pp) > TOLERANCE)
        repeat_rows.append({"subject": subject, "regime": LABELS[regime], "early_n": early.n, "late_n": late.n,
                            "early_bias": early.mean_signed_error_pp, "late_bias": late.mean_signed_error_pp,
                            "same_direction_with_n5": same_sign})
    repeats = pd.DataFrame(repeat_rows)
    repeat_table = format_table(repeats, {"subject": "포트폴리오", "regime": "상황", "early_n": "전반 n", "late_n": "후반 n",
        "early_bias": "전반 실제−추정 %p", "late_bias": "후반 실제−추정 %p", "same_direction_with_n5": "각 n≥5·같은 방향"})
    comparisons = summary[summary.kind == "portfolio"].copy()
    comparisons["label"] = comparisons.regime.map(LABELS)
    comparisons["model_label"] = comparisons.model.map(MODEL_LABELS)
    compare_table = format_table(comparisons, {"subject": "포트폴리오", "label": "상황", "model_label": "모델", "n": "n",
        "mae_pp": "MAE %p", "mean_signed_error_pp": "실제−추정 %p"})
    worst_view = worst.copy()
    worst_view["label"] = worst_view.regime.map(LABELS)
    worst_table = format_table(worst_view, {"subject": "포트폴리오", "start": "시작", "end": "종료", "label": "상황",
        "predicted_loss_pct": "추정 손실 %", "actual_loss_pct": "실제 손실 %", "underestimate_pp": "실제−추정 %p"})
    sensitivity_ranges = sensitivity.groupby(["subject", "regime"]).agg(min_n=("n", "min"), max_n=("n", "max"),
        min_mae=("mae_pp", "min"), max_mae=("mae_pp", "max"), min_bias=("mean_signed_error_pp", "min"), max_bias=("mean_signed_error_pp", "max")).reset_index()
    sensitivity_ranges["label"] = sensitivity_ranges.regime.map(LABELS)
    sensitivity_table = format_table(sensitivity_ranges, {"subject": "포트폴리오", "label": "상황", "min_n": "최소 n", "max_n": "최대 n",
        "min_mae": "최소 MAE %p", "max_mae": "최대 MAE %p", "min_bias": "최소 실제−추정 %p", "max_bias": "최대 실제−추정 %p"})
    sensitivity_notes = []
    for subject in focal.subject.unique():
        by_regime = repeats[repeats.subject == subject].set_index("regime")
        remainder = by_regime.loc[LABELS["neither"]]
        rate = by_regime.loc[LABELS["rate_up"]]
        rate_range = sensitivity_ranges[(sensitivity_ranges.subject == subject) & (sensitivity_ranges.regime == "rate_up")].iloc[0]
        rate_full = focal[(focal.subject == subject) & (focal.regime == "rate_up")].iloc[0]
        sensitivity_notes.append(
            f"- {subject}: 두 기준 모두 미충족 상황의 평균 실제−추정은 전반 {remainder.early_bias:+.2f}%p / 후반 {remainder.late_bias:+.2f}%p입니다. "
            f"금리 급등 기준만 충족 상황은 전반 {rate.early_bias:+.2f}%p / 후반 {rate.late_bias:+.2f}%p이며, "
            f"9개 정의의 전체 기간 편향 범위는 {rate_range.min_bias:+.2f}~{rate_range.max_bias:+.2f}%p입니다."
        )
        sensitivity_notes.append(
            f"- {subject}: 기본 금리 급등 상황의 전체 평균 실제−추정은 {rate_full.mean_signed_error_pp:+.2f}%p지만, "
            f"실제 손실 {int(rate_full.actual_loss_n)}개 구간에서는 {rate_full.actual_loss_mean_signed_error_pp:+.2f}%p, "
            f"실제 이익 {int(rate_full.actual_gain_n)}개 구간에서는 {rate_full.actual_gain_mean_signed_error_pp:+.2f}%p입니다. "
            "전체 평균이 추정을 보수적으로 보이게 하더라도 실제 손실 구간까지 보수적이라고 볼 수 없습니다."
        )
    cross_table = format_table(cross_view[cross_view.n >= SMALL_SAMPLE].sort_values(["subject", "mae_pp"], ascending=[True, False]),
        {"subject": "포트폴리오", "label": "세부 상황", "n": "n", "mae_pp": "MAE %p",
         "mean_signed_error_pp": "평균 실제−추정 %p", "actual_loss_n": "실제 손실 n",
         "predicted_gain_actual_loss_count": "이익 추정·실제 손실 횟수"})
    (OUT / "stress_validation_report.md").write_text(f"""# Stress 검증: 상황별 오차 분석

**기존 첫 수정 모델을 재학습하지 않고 상황별 실패 양상을 진단했습니다.**
대상은 {intervals.start.min()}~{intervals.end.max()}의 비중첩 10거래일 구간 {len(intervals)}개, 28개 자산과 변경 전·후 예시 포트폴리오입니다.
이번 결과는 사후 진단이며, 해당 상황을 미리 식별하는 성능이나 새로운 홀드아웃의 정확도가 아닙니다.
기존의 별도 고정 위기 사례는 이 145개 구간에 추가 합산하지 않았습니다. 따라서 2020년 코로나 사례는 이 기간 분류의 표본 수에 포함되지 않습니다.

## 주요 관측

{chr(10).join(observations)}

표본이 작은 동반 충격이나 기준에 민감한 구간의 평균만으로 새 모델·보정 계수를 채택하지 않습니다.
아래의 방향·전후반·기준 민감도를 함께 보고 반복되는 관측과 가설을 구분해야 합니다.

## 다음 수정에 대한 판단

{chr(10).join(sensitivity_notes)}

기본 분류에서 반복된 방향이 있더라도 임계값 변경·기간 분할에서 방향이 달라지면 전체에 같은 보정값을 더하거나 빼는 방식의 근거로 사용하기 어렵습니다.
따라서 이번 진단만으로 상황별 모델 전환이나 고정 편향 보정을 추가하지 않습니다. 우선 첫 수정 모델을 고정하고 새 기간의 상황별 오차를 누적하며, 과거 자료만으로 산출한 오차 범위의 실제 포함률을 별도 검증하는 것이 다음 후보입니다. 오차 범위나 포함률 자체를 이번 작업에서 계산한 것은 아닙니다.

## 상황 정의와 전체 오차 분해

- 주식 급락: 관측된 10일 SPY 수익률 ≤ −5%.
- 금리 급등: 같은 10일 DGS10 변화 ≥ +20bp.
- 동반 충격 / 주식 급락 기준만 충족 / 금리 급등 기준만 충족 / 두 기준 모두 미충족의 네 가지로 서로 겹치지 않게 분류합니다.
- ‘기준만 충족’은 다른 시장 변화가 없었다는 뜻이 아닙니다. ‘두 기준 모두 미충족’도 정상·안전 판정이 아닙니다.
- 이 임계값은 이번 진단용 고정 규칙이며 업계 표준·보정된 경보 기준이 아닙니다. 결과에 맞춰 선택하지 않았고 아래의 고정 3×3 민감도 비교도 모두 공개합니다.

양수 손실, 음수 이익입니다. `실제−추정`이 양수이면 실제 결과가 더 손실 쪽에 있음을 뜻하며, 실제가 이익인 구간에서는 이익을 과대 추정한 경우도 포함합니다.
실제 손실 구간만의 과소추정은 별도 열로 제시합니다. n=0은 N/A, n<5는 작은 표본으로 표시합니다. n≥5도 통계적 신뢰성이 확보됐다는 뜻은 아닙니다.

{table}

전체 절대오차 기여도는 `상황 내 Σ|실제−추정| / 전체 Σ|실제−추정|`입니다. 네 상황의 구간 수와 절대오차 합은 전체와 일치합니다.
MAE가 큰 상황과 전체 오차를 많이 차지하는 상황은 표본 비중 때문에 다를 수 있습니다.

### 실제 손실·이익을 구분하면 방향이 같은가

{outcome_table}

실제 결과의 부호로 나눈 사후 조건부 진단입니다. 이익 구간에서 큰 음의 편향이 나타나 전체 평균을 낮추는 동안 실제 손실 구간의 평균 편향은 양수일 수 있습니다.
이 결과만으로 원인이나 사전 식별 가능성을 주장하지 않으며, 전체 평균을 0에 맞추는 보정이 실제 손실 구간도 개선한다는 근거로 사용하지 않습니다.

[상황별 MAE 차트](stress_validation_mae_comparison.html) · [상황별 방향 차트](stress_validation_bias_comparison.html)
[전체 자산·모델 집계](stress_validation_regime_summary.csv) · [분류·오차 원행](stress_validation_rows.csv) · [145개 구간 분류](stress_validation_intervals.csv)

## 시간적으로 같은 방향이 반복되는가

시간순 전반 {len(intervals)//2}개와 후반 {len(intervals)-len(intervals)//2}개로 나누었습니다.
각 구간에서 같은 상황의 평균 편향 방향이 같고 양쪽 n≥5인지를 기술적으로 확인합니다. 통계적 유의성·시간적 안정성의 증명은 아닙니다.
한쪽 n<5이거나 편향 방향이 달라지면 반복되는 일반 규칙으로 판단하지 않습니다.

{repeat_table}

[전후반 전체 집계](stress_validation_period_summary.csv)

## 기준 변경에 민감한가

주식 하락 기준 −3% / −5% / −7%, 금리 상승 기준 +10 / +20 / +30bp의 9개 조합을 모두 비교했습니다.
아래 최솟값·최댓값은 서로 다른 표본의 기술통계 범위이며 신뢰구간이 아닙니다. 희소 구간도 포함하므로 n 범위를 함께 봐야 합니다.
평균 편향 범위가 0을 가로지르면 방향이 기준에 따라 바뀌는 것이므로 고정된 보정 방향을 주장할 수 없습니다.

{sensitivity_table}

[9개 기준별 원 집계](stress_validation_sensitivity.csv)

## 비교 모델과 더 세밀한 구간

첫 수정·기존 시장 단일팩터·주식+금리+VIX·단순 SPY를 같은 상황과 날짜로 비교했습니다. 상황별로 유리한 모델을 사후 골라 운용하지 않습니다.

{compare_table}

보조적으로 SPY 수익률 ≤−5%, (−5%,−2%], (−2%,+2%), [+2%,+5%), ≥+5%의 5개 구간과
금리 변화 ≤−20bp, (−20bp,+20bp), ≥+20bp의 3개 구간을 교차했습니다. 경계는 코드와 CSV에 그대로 남겼습니다.
[5×3 교차 집계](stress_validation_cross_summary.csv)의 15개 셀은 완전 분할이며, 네 기본 상황 집계와 중복해 합산하지 않습니다.

아래는 각 n≥5인 세부 셀만 표시한 것입니다. 이 조건을 충족하지 않는 나머지 셀도 원 CSV에는 남겨 두었습니다.

{cross_table}

## 큰 오차의 실제 날짜

포트폴리오별 절대오차 상위 10개 구간입니다. 큰 오차를 확인하기 위한 사후 목록이며 별도 검증 표본이 아닙니다.

{worst_table}

[큰 오차 원행](stress_validation_worst_windows.csv)

## 해석·범위·재현

원천 결과는 이미 학습 종료일이 평가 시작일보다 앞서는 첫 수정의 고정 추론 기록입니다. 이번 작업은 재학습·임계값 튜닝·운영 엔진 변경을 수행하지 않습니다.
상황은 평가 구간에서 실제로 일어난 시장 움직임으로 정의했습니다. 주가·금리 충격, 변동성, 종목 고유 요인과 모형 오차의 인과관계를 이 분류만으로 확정할 수 없습니다.
28개 현재 지원 자산, 현재 정한 예시 비중, 수정된 저장 스냅샷의 한계를 상속합니다. 생존편향·당시 공표 시각을 해소한 검증이 아닙니다.
145개 결과 구간은 겹치지 않지만 기초 모델의 학습창은 겹칩니다. 개별 자산·모델 행을 독립 표본으로 합산하지 않습니다.

```bash
python -m analysis.portfolio_regime_stress_diagnostics
python -m pytest tests/test_portfolio_regime_stress_diagnostics.py
```

[원천 해시·고정 정의](stress_validation_manifest.json) · [검사 기록](stress_validation_checks.json)
차트는 Data 표준 렌더러로 생성합니다. JSON 검사와 실제 브라우저 표시 검사는 구분합니다.
""")


def main():
    sources = [SOURCE, ROOT / "reports/portfolio/joint_stress/manifest.json"]
    upstream = json.loads(sources[1].read_text())
    for name, digest in upstream["inputs_sha256"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"upstream source changed: {name}")
    raw = pd.read_csv(SOURCE)
    rows, intervals = prepare_rows(raw)
    summary = summarize(rows, "regime", REGIMES)
    cross_levels = [m + "__" + r for m, r in itertools.product(MARKET_BINS, RATE_BINS)]
    cross = summarize(rows, "cross_regime", cross_levels)
    periods = period_summary(rows)
    sensitivity = threshold_sensitivity(rows)
    worst = pd.concat([g.nlargest(10, "absolute_error_pp") for _, g in
                       rows[(rows.kind == "portfolio") & (rows.model == FOCAL)].groupby("subject")])
    OUT.mkdir(parents=True, exist_ok=True)
    for name, frame in (("rows", rows), ("intervals", intervals), ("regime_summary", summary), ("cross_summary", cross),
                        ("period_summary", periods), ("sensitivity", sensitivity), ("worst_windows", worst)):
        frame.to_csv(OUT / f"stress_validation_{name}.csv", index=False, float_format="%.12g")
    manifest = {"sources_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        "upstream_inputs_sha256": upstream["inputs_sha256"],
        "runtime": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__},
        "method": {"focal_model": FOCAL, "comparators": list(MODELS[1:]), "equity_cutoff": EQUITY_CUTOFF,
                   "rate_cutoff_bp": RATE_CUTOFF, "small_sample_threshold": SMALL_SAMPLE,
                   "sensitivity_equity_cutoffs": [-0.03, -0.05, -0.07], "sensitivity_rate_cutoffs_bp": [10, 20, 30],
                   "regimes_use_realized_outcomes": True, "new_holdout": False, "refitting": False,
                   "period_split": "chronological first 72 vs last 73 intervals", "positive_error": "actual minus estimated loss"},
        "coverage": {"intervals": len(intervals), "selected_rows": len(rows), "regime_summary_rows": len(summary),
                     "cross_summary_rows": len(cross), "period_summary_rows": len(periods), "sensitivity_rows": len(sensitivity)}}
    (OUT / "stress_validation_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    for name, metric, title in (("mae", "mae_pp", "Stress 검증: 상황별 평균 절대오차"),
                                ("bias", "mean_signed_error_pp", "Stress 검증: 상황별 실제 손실−추정 손실")):
        (OUT / f"stress_validation_{name}_comparison.json").write_text(json.dumps(chart_config(summary, metric, title), indent=2, ensure_ascii=False) + "\n")
    write_report(summary, periods, sensitivity, worst, intervals, cross)
    print(summary[(summary.kind == "portfolio") & (summary.model == FOCAL)].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
