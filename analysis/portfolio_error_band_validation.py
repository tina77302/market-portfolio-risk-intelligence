"""Stress 검증: chronological historical-error loss bands, not guaranteed CIs.

    python -m analysis.portfolio_error_band_validation
"""

import hashlib
import json
import math
import platform
from pathlib import Path

import numpy as np
import pandas as pd

from analysis.portfolio_regime_stress_diagnostics import FOCAL, LABELS, REGIMES, classify
from analysis.portfolio_stress_validation import markdown_table

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/portfolio/error_band_stress"
SOURCE = ROOT / "reports/portfolio/joint_stress/rolling.csv"
TARGET = 0.90
MAX_ERRORS = 60
MIN_ERRORS = 30
METHODS = ("signed_errors", "symmetric_absolute_errors")
METHOD_LABELS = {"signed_errors": "비대칭 과거 오차 범위", "symmetric_absolute_errors": "대칭 절대오차 범위"}


def error_offsets(errors, method, target=TARGET):
    """Explicit finite-sample order statistics; no exchangeability guarantee.

    Signed residual bounds use floor((n+1)*alpha/2) and
    ceil((n+1)*(1-alpha/2)), one-based and clamped to observed endpoints.
    The symmetric comparator uses ceil((n+1)*target) on |error|.
    """
    errors = np.asarray(errors, dtype=float)
    if errors.ndim != 1 or not len(errors) or not np.isfinite(errors).all():
        raise ValueError("finite, nonempty one-dimensional errors required")
    if not 0 < target < 1:
        raise ValueError("target coverage must be between zero and one")
    n = len(errors)
    if method == "signed_errors":
        low_rank = max(1, math.floor((n + 1) * (1 - target) / 2 + 1e-12))
        high_rank = min(n, math.ceil((n + 1) * (1 + target) / 2 - 1e-12))
        ordered = np.sort(errors)
        return float(ordered[low_rank - 1]), float(ordered[high_rank - 1]), low_rank, high_rank
    if method == "symmetric_absolute_errors":
        rank = min(n, math.ceil((n + 1) * target - 1e-12))
        radius = float(np.sort(np.abs(errors))[rank - 1])
        return -radius, radius, rank, rank
    raise ValueError("unknown error-band method")


def make_bands(source, min_errors=MIN_ERRORS, max_errors=MAX_ERRORS, target=TARGET):
    if not 1 <= min_errors <= max_errors:
        raise ValueError("calibration minimum must be positive and <= maximum")
    required = ["subject", "kind", "start", "end", "predicted_loss_pct", "actual_loss_pct", "shock_market", "shock_rate"]
    data = source.loc[source.model == FOCAL, required].copy()
    if data.empty or data[required].isna().any().any() or data.duplicated(["subject", "start", "end"]).any():
        raise ValueError("empty, missing or duplicate focal predictions")
    if not np.isfinite(data[required[4:]].to_numpy()).all():
        raise ValueError("nonfinite loss or shock")
    data = data.sort_values(["subject", "start"]).reset_index(drop=True)
    intervals = data[["start", "end"]].drop_duplicates().sort_values("start").reset_index(drop=True)
    if intervals.duplicated("start").any() or (intervals.start >= intervals.end).any():
        raise ValueError("invalid outcome dates")
    if any(intervals.iloc[i].start < intervals.iloc[i - 1].end for i in range(1, len(intervals))):
        raise ValueError("overlapping outcome windows")
    period = {start: "early" if i < len(intervals) // 2 else "late" for i, start in enumerate(intervals.start)}
    data["regime"] = classify(data.shock_market, data.shock_rate)
    data["period"] = data.start.map(period)
    output = []
    for subject, history in data.groupby("subject", sort=False):
        if len(history) != len(intervals) or history.start.to_list() != intervals.start.to_list():
            raise ValueError("subjects do not share the same intervals")
        for row in history.itertuples(index=False):
            # Even a window ending exactly on start is deliberately excluded.
            past = history[history.end < row.start].tail(max_errors)
            n = len(past)
            ready = n >= min_errors
            for method in METHODS:
                record = {
                    "subject": subject, "kind": row.kind, "model": FOCAL, "method": method,
                    "start": row.start, "end": row.end, "period": row.period, "regime": row.regime,
                    "predicted_loss_pct": row.predicted_loss_pct, "actual_loss_pct": row.actual_loss_pct,
                    "target_coverage": target, "calibration_n": n, "ready": ready,
                    "calibration_first_start": past.start.iloc[0] if n else None,
                    "calibration_last_end": past.end.iloc[-1] if n else None,
                    "lower_offset_pp": np.nan, "upper_offset_pp": np.nan,
                    "lower_rank": np.nan, "upper_rank": np.nan,
                    "lower_loss_pct": np.nan, "upper_loss_pct": np.nan, "width_pp": np.nan,
                    "covered": None, "upper_breach": None, "lower_breach": None,
                    "upper_excess_pp": np.nan, "lower_excess_pp": np.nan, "interval_score": np.nan,
                }
                if ready:
                    errors = past.actual_loss_pct.to_numpy() - past.predicted_loss_pct.to_numpy()
                    lower_offset, upper_offset, lo_rank, hi_rank = error_offsets(errors, method, target)
                    lower = row.predicted_loss_pct + lower_offset
                    upper = row.predicted_loss_pct + upper_offset
                    above, below = max(row.actual_loss_pct - upper, 0), max(lower - row.actual_loss_pct, 0)
                    width = upper - lower
                    record.update(lower_offset_pp=lower_offset, upper_offset_pp=upper_offset,
                                  lower_rank=lo_rank, upper_rank=hi_rank, lower_loss_pct=lower, upper_loss_pct=upper,
                                  width_pp=width, covered=bool(lower <= row.actual_loss_pct <= upper),
                                  upper_breach=bool(row.actual_loss_pct > upper), lower_breach=bool(row.actual_loss_pct < lower),
                                  upper_excess_pp=above, lower_excess_pp=below,
                                  interval_score=width + 2 / (1 - target) * (above + below))
                output.append(record)
    return pd.DataFrame(output)


def band_metrics(group):
    ready = group[group.ready]
    losses = ready[ready.actual_loss_pct > 0]
    upper = ready[ready.upper_breach == True]  # noqa: E712
    return {
        "total_n": len(group), "evaluated_n": len(ready), "warmup_n": len(group) - len(ready),
        "small_sample": len(ready) < 5,
        "covered_n": int(ready.covered.sum()), "empirical_coverage": ready.covered.mean() if len(ready) else np.nan,
        "upper_breach_n": len(upper), "lower_breach_n": int(ready.lower_breach.sum()),
        "upper_breach_fraction": ready.upper_breach.mean() if len(ready) else np.nan,
        "mean_width_pp": ready.width_pp.mean(), "median_width_pp": ready.width_pp.median(),
        "mean_interval_score": ready.interval_score.mean(),
        "mean_upper_excess_all_pp": ready.upper_excess_pp.mean(),
        "mean_upper_excess_when_breached_pp": upper.upper_excess_pp.mean(),
        "max_upper_excess_pp": ready.upper_excess_pp.max(),
        "actual_loss_n": len(losses),
        "actual_loss_coverage": losses.covered.mean() if len(losses) else np.nan,
        "actual_loss_upper_breach_n": int(losses.upper_breach.sum()),
    }


def summarize(rows, dimension=None, levels=None):
    result = []
    for (subject, kind, method), data in rows.groupby(["subject", "kind", "method"], sort=False):
        for level in levels if dimension else [None]:
            group = data[data[dimension] == level] if dimension else data
            result.append({"subject": subject, "kind": kind, "method": method,
                           **({dimension: level} if dimension else {}), **band_metrics(group)})
    return pd.DataFrame(result)


def chart_config(rows, subject):
    view = rows[(rows.subject == subject) & (rows.method == "signed_errors")].sort_values("start")
    return {"id": "stress-validation-error-band-" + subject,
        "title": "과거 오차 범위와 실제 손실: " + ("변경 전" if subject == "before" else "TLT 30%"),
        "height": 400, "description": "목표 포함률 90%의 과거오차 기반 상·하한, 미래 보장 아님. 양수 손실·음수 이익. 최초 31개 구간은 자료 부족으로 범위 미확인.",
        "spec": {"type": "line", "x": "end", "y": ["추정 손실", "하한", "상한", "실제 손실"], "yLabel": "손실 (%)",
                 "startAtZero": False, "valueFormat": {"style": "decimal", "maximumFractionDigits": 2}},
        "rows": [{"end": r.end, "추정 손실": float(r.predicted_loss_pct), "실제 손실": float(r.actual_loss_pct),
                  "하한": float(r.lower_loss_pct) if r.ready else None, "상한": float(r.upper_loss_pct) if r.ready else None}
                 for r in view.itertuples()]}


def table(frame, columns):
    return markdown_table(frame, columns).replace("nan", "N/A")


def write_report(rows, overall, regimes, periods, breaches):
    view = overall[overall.kind == "portfolio"].copy()
    view["label"] = view.method.map(METHOD_LABELS)
    view["coverage_pct"] = view.empirical_coverage * 100
    view["loss_coverage_pct"] = view.actual_loss_coverage * 100
    main_table = table(view, {"subject": "포트폴리오", "label": "범위 방식", "evaluated_n": "평가 n", "warmup_n": "미확인 n",
        "coverage_pct": "실제 포함률 %", "mean_width_pp": "평균 폭 %p", "upper_breach_n": "상한 초과 횟수",
        "mean_upper_excess_when_breached_pp": "초과 시 평균 초과폭 %p", "mean_interval_score": "구간 점수"})
    group = regimes[(regimes.kind == "portfolio") & (regimes.method == "signed_errors")].copy()
    group["label"] = group.regime.map(LABELS)
    group["coverage_pct"] = group.empirical_coverage * 100
    regime_table = table(group, {"subject": "포트폴리오", "label": "상황", "total_n": "전체 n", "evaluated_n": "평가 n",
        "coverage_pct": "포함률 %", "mean_width_pp": "평균 폭 %p", "upper_breach_n": "상한 초과", "small_sample": "평가 n<5"})
    period_view = periods[(periods.kind == "portfolio") & (periods.method == "signed_errors")].copy()
    period_view["coverage_pct"] = period_view.empirical_coverage * 100
    period_table = table(period_view, {"subject": "포트폴리오", "period": "기간", "evaluated_n": "평가 n", "warmup_n": "미확인 n",
        "coverage_pct": "포함률 %", "mean_width_pp": "평균 폭 %p", "upper_breach_n": "상한 초과"})
    observations = []
    for subject in ("before", "after"):
        selected = view[view.subject == subject].set_index("method")
        primary, comparator = selected.loc["signed_errors"], selected.loc["symmetric_absolute_errors"]
        observations.append(f"- {subject}: 비대칭 범위는 {int(primary.covered_n)}/{int(primary.evaluated_n)}개, **{primary.coverage_pct:.1f}%**를 포함했습니다. 평균 폭 {primary.mean_width_pp:.2f}%p, 상한 초과 {int(primary.upper_breach_n)}개입니다. 대칭 범위는 {comparator.coverage_pct:.1f}% / 폭 {comparator.mean_width_pp:.2f}%p입니다.")
        observations.append(f"- {subject}: 실제 손실 {int(primary.actual_loss_n)}개 구간에 한정하면 비대칭 포함률은 {primary.loss_coverage_pct:.1f}%, 대칭은 {comparator.loss_coverage_pct:.1f}%입니다. 전체 포함률이 손실 구간의 포함률까지 보장하지 않습니다.")
        if comparator.mean_width_pp < primary.mean_width_pp and comparator.empirical_coverage > primary.empirical_coverage and comparator.mean_interval_score < primary.mean_interval_score:
            observations.append(f"- {subject}: 이 표본에서 대칭 방식은 더 좁은 폭·높은 포함률·낮은 구간 점수를 보였습니다. 이는 동일 과거 표본에서의 비교 결과이며 새 기간에서도 우위라는 결론이나 자동 채택 근거로 쓰지 않습니다.")
    exceed_table = table(breaches, {"subject": "포트폴리오", "start": "시작", "end": "종료", "calibration_n": "과거 오차 n",
        "predicted_loss_pct": "점 추정 %", "upper_loss_pct": "상한 %", "actual_loss_pct": "실제 손실 %", "upper_excess_pp": "상한 초과 %p"})
    example = rows[(rows.subject == "before") & (rows.method == "signed_errors") & rows.ready].iloc[0]
    (OUT / "stress_validation_report.md").write_text(f"""# Stress 검증: 과거 오차 범위와 실제 포함률

**구현·검증 완료. 범위를 계산할 수 있으나 미래 포함률 보장이나 운영 채택을 뜻하지 않습니다.**
첫 수정의 주식+금리 점 추정값은 유지하고, 과거에 확정된 오차로 상·하한을 추가했습니다.
모델과 범위 규칙은 이미 확인한 145개 구간에서 사후 설계했습니다. 시간순 계산을 지켰어도 새 미사용 홀드아웃은 아닙니다.

## 주요 결과

{chr(10).join(observations)}

{main_table}

포함 목표는 90%이지만 위 값은 실제 검증 결과입니다. 평가 가능한 구간만 분모에 넣고 자료 부족 구간을 성공·실패로 채우지 않았습니다.
목표 이상 포함률만으로 좋은 범위라고 판단하지 않습니다. 폭·상한 초과폭·구간 점수와 기간·상황별 결과를 함께 봅니다.

[변경 전 추이](stress_validation_before_comparison.html) · [TLT 편입 후 추이](stress_validation_after_comparison.html)
[전체 자산 집계](stress_validation_summary.csv) · [상·하한·보정 표본 날짜·실제 결과](stress_validation_rows.csv)

## 범위 계산 규칙

- 대상: 첫 수정 모델의 고정 10거래일 점 추정과 실제 손실. 자산·포트폴리오 각각 별도의 오차 이력을 사용하며 서로 합쳐 표본을 늘리지 않습니다.
- 잔차: `실제 손실 − 점 추정`, 단위 %p.
- 평가 시작일보다 **종료일이 엄격히 이전**인 과거 구간만 선택합니다. 평가 시작일에 끝난 직전 구간도 기존 정책과 같이 제외합니다.
- 그중 최근 최대 {MAX_ERRORS}개, 최소 {MIN_ERRORS}개의 오차를 요구합니다. 부족하면 상·하한과 포함 여부는 N/A입니다. 전체 145개 중 최초 31개는 준비 구간, 나머지 114개는 평가 가능합니다.
- 90% 목표 비대칭 범위: 오차를 정렬하고 1부터 세는 하한 순위 `floor((n+1)×0.05)`, 상한 순위 `ceil((n+1)×0.95)`를 사용합니다. 순위는 실제 표본 1~n으로 제한하며 관측값 사이를 보간하지 않습니다.
- 범위 = `점 추정 + [과거 오차 하한, 과거 오차 상한]`. 점 추정은 보정하거나 이동하지 않습니다. 범위가 점 추정을 반드시 중심 또는 내부에 포함하도록 억지로 넓히지 않습니다.
- 대칭 비교 범위: 절대오차의 `ceil((n+1)×0.90)`번째 값(최대 n)을 반경으로 사용해 `점 추정 ± 반경`을 계산합니다. 같은 과거 표본·시점·준비 기간을 사용합니다.
- 음수 하한은 이익을 뜻하며 0으로 자르지 않습니다. 고정 규칙·목표·최소 표본·최대 창을 결과에 맞춰 바꾸지 않았습니다.

최초 평가 사례: 시작일 {example.start}, 마지막 보정 구간 종료일 {example.calibration_last_end}, 보정 표본 {int(example.calibration_n)}개입니다.
일반적인 독립·동일분포 오차나 교환 가능성을 확인한 자료가 아니므로 위 순위 공식에 유한표본 미래 보장을 붙이지 않습니다. 시계열 의존·분포 변화가 남습니다.

## 폭과 실패의 평가

상한 초과는 `실제 손실 > 상한`, 초과폭은 `max(실제 손실−상한, 0)`입니다. 상한은 최대 손실 한도가 아닙니다.
하한보다 실제가 작으면 하한 이탈로 따로 셉니다. 양끝과 같은 값은 포함으로 처리합니다.
구간 점수는 `폭 + 2/0.1 × (상한 초과폭 + 하한 이탈폭)`입니다. 넓은 범위와 큰 이탈을 함께 불리하게 평가하며 낮을수록 좋습니다.
이 점수로 사후 파라미터나 방식의 승자를 튜닝하지 않았습니다. 지표별 장단점을 그대로 보고합니다.

실제 손실이 난 구간만의 포함률도 [전체 집계 CSV](stress_validation_summary.csv)에 별도 제공합니다. 이는 실제 결과에 따른 조건부 진단이며 사전 식별 규칙이 아닙니다.

## 시간·상황별 포함률

기존 진단과 같은 전반 72개 / 후반 73개 분할을 사용합니다. 준비 기간 때문에 평가 표본 수는 다르며 이를 표에 표시합니다.

{period_table}

상황은 사후 관측한 SPY 10일 수익률 ≤−5%, 금리 변화 ≥+20bp로 나눕니다. 상황별로 범위 규칙이나 보정 오차를 별도 선택하지 않았습니다.
n<5는 작은 표본으로 표시합니다. 작은 상황의 100% 포함이나 N/A를 높은 신뢰성으로 해석하지 않습니다.

{regime_table}

[기간별 전체 집계](stress_validation_period_summary.csv) · [상황별 전체 집계](stress_validation_regime_summary.csv)

## 상한을 넘긴 실제 사례

비대칭 방식의 예시 포트폴리오 상한 초과 구간 중 초과폭 상위 최대 10개씩입니다. 추가 평가 표본이 아니라 위 평가 결과의 부분집합입니다.

{exceed_table}

[상한 초과 원행](stress_validation_upper_breaches.csv)

## 해석·재현·검사

입력은 고정 2026-10-23 스냅샷으로 생성한 기존 모델의 결과입니다. 현재 지원 자산군·수정종가·실제 시장 충격을 사후 입력한 조건부 재현의 한계를 상속합니다.
이 범위는 새 시나리오의 손실 보장·미래 확률·최대 손실이나 보정된 실시간 예측이 아닙니다. 모델 학습창과 보정창은 평가 시점 사이에 겹칩니다.
시나리오 충격을 미리 예측하는 성능도 검증하지 않았습니다. 운영 채택 전에 고정한 규칙으로 새 기간을 평가해야 합니다.

```bash
python -m analysis.portfolio_error_band_validation
python -m pytest tests/test_portfolio_error_band_validation.py
```

[입력 해시·방법 manifest](stress_validation_manifest.json) · [검사 기록](stress_validation_checks.json)
차트의 준비 구간은 하한·상한을 null로 남깁니다. 표준 렌더러의 JSON 검사와 실제 화면 검사는 구분합니다.
""")


def main():
    paths = [SOURCE, ROOT / "reports/portfolio/joint_stress/manifest.json"]
    upstream = json.loads(paths[1].read_text())
    for name, digest in upstream["inputs_sha256"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"upstream input changed: {name}")
    rows = make_bands(pd.read_csv(SOURCE))
    overall = summarize(rows)
    regimes = summarize(rows, "regime", REGIMES)
    periods = summarize(rows, "period", ("early", "late"))
    breach_source = rows[(rows.kind == "portfolio") & (rows.method == "signed_errors") & (rows.upper_breach == True)]  # noqa: E712
    breaches = pd.concat([g.nlargest(10, "upper_excess_pp") for _, g in breach_source.groupby("subject")]) if len(breach_source) else rows.iloc[:0]
    OUT.mkdir(parents=True, exist_ok=True)
    for name, frame in (("rows", rows), ("summary", overall), ("regime_summary", regimes), ("period_summary", periods), ("upper_breaches", breaches)):
        frame.to_csv(OUT / f"stress_validation_{name}.csv", index=False, float_format="%.12g")
    manifest = {"sources_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        "upstream_inputs_sha256": upstream["inputs_sha256"],
        "runtime": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__},
        "method": {"point_model": FOCAL, "target_coverage": TARGET, "minimum_errors": MIN_ERRORS, "maximum_errors": MAX_ERRORS,
                   "eligibility": "historical outcome end strictly before evaluation start", "error": "actual minus predicted loss, pp",
                   "methods": list(METHODS), "quantile_interpolation": False, "parameter_tuning": False,
                   "new_holdout": False, "future_coverage_guarantee": False, "production_adoption": False},
        "coverage": {"source_intervals": 145, "subjects": rows.subject.nunique(), "rows": len(rows),
                     "evaluated_per_subject_method": int(rows[rows.ready].groupby(['subject','method']).size().iloc[0]),
                     "warmup_per_subject_method": int(rows[~rows.ready].groupby(['subject','method']).size().iloc[0])}}
    (OUT / "stress_validation_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    for subject in ("before", "after"):
        (OUT / f"stress_validation_{subject}_comparison.json").write_text(json.dumps(chart_config(rows, subject), indent=2, ensure_ascii=False) + "\n")
    write_report(rows, overall, regimes, periods, breaches)
    print(overall[overall.kind == "portfolio"].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
