"""Stress 검증: replay stress losses with betas fitted strictly before each interval.

Run from the project root: python -m analysis.portfolio_stress_validation
No downloads, training artifact updates, or production scenario changes.
"""

import hashlib
import json
import platform
from pathlib import Path

import numpy as np
import pandas as pd

from src.portfolio.factors import build_factor_moves, estimate_betas

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "portfolio"
WINDOW = 756
MIN_OBSERVATIONS = 252
HORIZON = 10
FACTOR_SERIES = {"market": "SPY", "rate": "DGS10", "volatility": "VIX"}
CASE_NAMES = {
    "equity_selloff": "주식 급락",
    "rate_shock": "금리 급등",
    "volatility_shock": "변동성 급등",
}


def validate_inputs(prices, factors):
    for name, frame in (("prices", prices), ("factors", factors)):
        if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
            raise ValueError(f"{name}: dates must be unique and increasing")
        if frame.columns.has_duplicates:
            raise ValueError(f"{name}: duplicate columns")
    if not prices.index.equals(factors.index):
        raise ValueError("prices and factors must have exactly aligned dates")
    if prices.empty or not np.isfinite(prices.to_numpy()).all() or (prices <= 0).any().any():
        raise ValueError("prices must be finite, positive and complete")
    if "SPY" not in prices or not {"DGS10", "VIX"}.issubset(factors.columns):
        raise ValueError("SPY, DGS10 and VIX are required")
    if not np.isfinite(factors["VIX"]).all():
        raise ValueError("VIX must be finite and complete")
    if np.isinf(factors["DGS10"]).any():
        raise ValueError("DGS10 may be missing but cannot be infinite")


def load_portfolios():
    portfolios = {}
    for name in ("before", "after"):
        request = json.loads((ROOT / "examples" / "portfolio" / f"{name}.json").read_text())
        weights = {h["ticker"]: h["weight"] / 100 for h in request["holdings"]}
        if len(weights) != len(request["holdings"]) or not np.isclose(sum(weights.values()), 1):
            raise ValueError("demo weights must be unique and sum to 1")
        portfolios[name] = weights
    return portfolios


def subject_weights(prices, portfolios):
    subjects = {ticker: {ticker: 1.0} for ticker in prices.columns}
    for name, weights in portfolios.items():
        if name in subjects or not set(weights).issubset(prices.columns):
            raise ValueError("invalid portfolio name or holdings")
        values = np.array(list(weights.values()), dtype=float)
        if not np.isfinite(values).all() or (values < 0).any() or not np.isclose(values.sum(), 1):
            raise ValueError("portfolio weights must be finite, nonnegative and sum to 1")
        subjects[name] = weights
    return subjects


def realized_shock(prices, factors, start, end, factor):
    if factor == "market":
        return float(prices.at[end, "SPY"] / prices.at[start, "SPY"] - 1)
    series = factors[FACTOR_SERIES[factor]]
    # Match the production scenario's rate-level policy; only past levels are carried.
    if factor == "rate":
        series = series.ffill()
    value = series.at[end] - series.at[start]
    if not np.isfinite(value):
        raise ValueError("missing scenario endpoints")
    return float(value * (100 if factor == "rate" else 1))


def replay_interval(prices, factors, start, end, factor, portfolios,
                    window=WINDOW, min_observations=MIN_OBSERVATIONS):
    """Initial-weight buy-and-hold outcome; beta cutoff is strictly < start.

    The realized factor shock is supplied after the interval. This is a conditional
    sensitivity replay, not a shock forecast or a point-in-time data-vintage test.
    """
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    start_pos, end_pos = prices.index.get_loc(start), prices.index.get_loc(end)
    if end_pos - start_pos != HORIZON:
        raise ValueError("each outcome must span exactly 10 trading observations")
    if start_pos < 2:
        raise ValueError("not enough pre-event history")
    history = prices.iloc[:start_pos]
    historical_factors = factors.loc[history.index]
    returns, moves = build_factor_moves(history, historical_factors, window_days=window)
    if len(returns) < min_observations:
        raise ValueError("not enough pre-event returns")
    betas = estimate_betas(returns, moves)
    shock = realized_shock(prices, factors, start, end, factor)
    spy_loss = -100 * realized_shock(prices, factors, start, end, "market")
    endpoint_returns = prices.loc[end] / prices.loc[start] - 1
    subjects = subject_weights(prices, portfolios)
    rows = []
    for subject, weights in subjects.items():
        tickers = list(weights)
        w = np.array(list(weights.values()))
        n = int(betas.loc[tickers, f"{factor}_n"].min())
        if n < min_observations:
            raise ValueError(f"{subject}/{factor}: insufficient paired observations")
        beta = float(w @ betas.loc[tickers, factor].to_numpy())
        if not np.isfinite(beta):
            raise ValueError(f"{subject}/{factor}: beta is not finite")
        predicted = -100 * beta * shock
        actual = -100 * float(w @ endpoint_returns[tickers].to_numpy())
        rows.append({
            "subject": subject, "kind": "portfolio" if subject in portfolios else "asset",
            "factor": factor, "start": start.date().isoformat(), "end": end.date().isoformat(),
            "train_start": returns.index[0].date().isoformat(),
            "train_end": returns.index[-1].date().isoformat(),
            "training_returns": len(returns), "paired_observations": n,
            "full_756_window": len(returns) == window,
            "beta": beta, "realized_shock": shock,
            "predicted_loss_pct": predicted, "actual_loss_pct": actual,
            "spy_proxy_loss_pct": spy_loss,
            # Positive means actual loss exceeds the estimate, including predicted gains.
            "underestimate_pp": actual - predicted,
            "absolute_error_pp": abs(actual - predicted),
        })
    return pd.DataFrame(rows)


def replay_cases(prices, factors, scenarios, portfolios):
    results = []
    for scenario in scenarios:
        result = replay_interval(prices, factors, scenario["reference"]["start"],
                                 scenario["reference"]["end"], scenario["factor"], portfolios)
        result.insert(0, "scenario", scenario["id"])
        result["frozen_shock"] = scenario["shock"]
        results.append(result)
    return pd.concat(results, ignore_index=True)


def rolling_replay(prices, factors, portfolios, window=WINDOW):
    """All eligible non-overlapping 10-day intervals, anchored to window + 1.

    Unlike the two 2020 stress cases, this comparison requires a full 756-return
    lookback. Returns in adjacent outcome intervals do not overlap. Training
    windows do overlap; rows are not treated as independent statistical trials.
    """
    results = []
    for start_pos in range(window + 1, len(prices) - HORIZON, HORIZON):
        for factor in FACTOR_SERIES:
            results.append(replay_interval(
                prices, factors, prices.index[start_pos], prices.index[start_pos + HORIZON],
                factor, portfolios, window=window,
            ))
    if not results:
        raise ValueError("no eligible full-window validation intervals")
    return pd.concat(results, ignore_index=True)


def summarize(rows):
    summaries = []
    for (subject, kind, factor), group in rows.groupby(["subject", "kind", "factor"], sort=False):
        error = group["underestimate_pp"]
        losses = group[group["actual_loss_pct"] > 0]
        # Relative tail per subject, selected retrospectively for diagnostics only.
        tail = group.nlargest(max(1, int(np.ceil(len(group) * 0.1))), "actual_loss_pct")
        summaries.append({
            "subject": subject, "kind": kind, "factor": factor,
            "intervals": len(group),
            "mae_pp": group["absolute_error_pp"].mean(),
            "rmse_pp": np.sqrt((error ** 2).mean()),
            "mean_underestimate_pp": error.mean(),
            "zero_loss_baseline_mae_pp": group["actual_loss_pct"].abs().mean(),
            "spy_proxy_baseline_mae_pp": (group["actual_loss_pct"] - group["spy_proxy_loss_pct"]).abs().mean(),
            "actual_loss_intervals": len(losses),
            "loss_underestimate_fraction": (losses["underestimate_pp"] > 0).mean(),
            "worst_decile_intervals": len(tail),
            "worst_decile_mae_pp": tail["absolute_error_pp"].mean(),
            "worst_decile_mean_underestimate_pp": tail["underestimate_pp"].mean(),
        })
    return pd.DataFrame(summaries)


def chart_config(cases):
    rows = []
    for _, row in cases[cases["kind"] == "portfolio"].iterrows():
        rows.append({
            "case": f"{CASE_NAMES[row['scenario']]} · {'변경 전' if row['subject'] == 'before' else 'TLT 30%'}",
            "추정 손실": row["predicted_loss_pct"], "실제 손실": row["actual_loss_pct"],
        })
    return {
        "id": "stress-validation-stress-replay", "title": "Stress 검증: 충격 시작 전 베타의 추정 손실과 실제 손실",
        "height": 460,
        "description": "양수=손실, 음수=이익. 베타는 시작일 이전 자료만 사용. 충격은 사후 관측값. 2020년 두 구간은 3년 미만 학습이며 서로 겹침.",
        "spec": {"type": "bar", "x": "case", "y": ["추정 손실", "실제 손실"],
                 "yLabel": "손실 (%)", "showValues": True,
                 "valueFormat": {"style": "decimal", "maximumFractionDigits": 2},
                 "colors": {"추정 손실": "#2a78d6", "실제 손실": "#e34948"}},
        "rows": rows,
    }


def markdown_table(frame, columns):
    lines = ["| " + " | ".join(columns.values()) + " |",
             "| " + " | ".join("---" for _ in columns) + " |"]
    for _, row in frame.iterrows():
        cells = []
        for key in columns:
            value = row[key]
            cells.append(f"{value:.2f}" if isinstance(value, (float, np.floating)) else str(value))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def write_report(cases, rolling, summary, manifest):
    portfolios = cases[cases["kind"] == "portfolio"].copy()
    portfolios["case_label"] = portfolios["scenario"].map(CASE_NAMES)
    portfolios["portfolio_label"] = portfolios["subject"].map({"before": "변경 전", "after": "TLT 30%"})
    rolling_summary = summary[summary["kind"] == "portfolio"].copy()
    case_summary = cases.groupby("scenario", sort=False).agg(
        assets=("kind", lambda k: (k == "asset").sum()),
        train_end=("train_end", "first"), training_returns=("training_returns", "first"),
        paired_observations=("paired_observations", "min"),
    ).reset_index()
    table = markdown_table(portfolios, {
        "case_label": "충격", "portfolio_label": "포트폴리오", "predicted_loss_pct": "추정 손실 %",
        "actual_loss_pct": "실제 손실 %", "underestimate_pp": "실제−추정 %p",
    })
    summary_table = markdown_table(rolling_summary, {
        "subject": "포트폴리오", "factor": "단일 팩터", "intervals": "10일 구간 수",
        "mae_pp": "MAE %p", "zero_loss_baseline_mae_pp": "0손실 기준 MAE %p",
        "spy_proxy_baseline_mae_pp": "SPY 대용 MAE %p",
        "mean_underestimate_pp": "평균 실제−추정 %p",
        "worst_decile_mae_pp": "손실 상위 10% MAE %p",
    })
    case_table = markdown_table(case_summary, {
        "scenario": "사례", "train_end": "학습 종료일", "training_returns": "학습 일간 수익률 수",
        "paired_observations": "최소 유효 회귀 표본 수", "assets": "자산 수",
    })
    first, last = rolling["start"].min(), rolling["end"].max()
    by_case = portfolios.set_index(["scenario", "subject"])
    by_summary = summary.set_index(["subject", "factor"])
    equity = by_case.loc[("equity_selloff", "before")]
    vol = by_case.loc[("volatility_shock", "before")]
    rate_before = by_case.loc[("rate_shock", "before")]
    rate_after = by_case.loc[("rate_shock", "after")]
    market_before = by_summary.loc[("before", "market")]
    market_after = by_summary.loc[("after", "market")]
    signed_loss = lambda value: f"{abs(value):.2f}% {'손실' if value >= 0 else '이익'}"
    asset_summary = cases[cases["kind"] == "asset"].groupby("scenario", sort=False).agg(
        mae_pp=("absolute_error_pp", "mean"),
        mean_underestimate_pp=("underestimate_pp", "mean"),
        underestimates=("underestimate_pp", lambda s: int((s > 0).sum())),
    ).reset_index()
    asset_table = markdown_table(asset_summary, {
        "scenario": "사례", "mae_pp": "28개 자산 MAE %p",
        "mean_underestimate_pp": "평균 실제−추정 %p", "underestimates": "손실 과소 추정 자산 수 / 28",
    })
    report = f"""# Stress 검증: 추정 손실과 실제 손실 비교

## 판정과 검증 범위

**한계 명시 후 공유 가능(Share with caveats). 검증 계산은 완료했으며, 정밀한 총손실 예측기로 사용할 근거는 부족합니다.**

고정 스냅샷의 28개 자산과 기존 변경 전·후 포트폴리오를 검증했습니다.
이는 충격을 미리 예측하는 백테스트가 아니라, **충격 시작 전 추정한 베타에 사후 관측한 충격을 넣었을 때의 조건부 손실 재현력** 검증입니다.
세 고정 위기 구간과 별도로, {first}~{last}의 겹치지 않는 10거래일 구간을 전수 비교했습니다.
현재 시연의 2023~2026년 베타를 2020년 손실 검증에 사용하지 않았습니다.

## 주요 결과와 적용 범위

1. **고정 위기 구간의 추정과 실제를 구분해야 합니다.** 변경 전 포트폴리오의 주식 급락 결과는 추정 {signed_loss(equity['predicted_loss_pct'])} / 실제 {signed_loss(equity['actual_loss_pct'])}입니다. 변동성 충격 결과는 추정 {signed_loss(vol['predicted_loss_pct'])} / 실제 {signed_loss(vol['actual_loss_pct'])}입니다. 두 구간의 실제−추정 차이는 각각 {equity['underestimate_pp']:+.2f}%p / {vol['underestimate_pp']:+.2f}%p입니다. 오차 방향이 음수이면 앞선 팩터 베타 분석의 “위기 손실을 작게 추정했을 수 있다”는 가설과 달리 과대 추정한 사례입니다.
2. **금리 단일 팩터와 실제 총손실 사이에 큰 잔차가 있습니다.** 변경 전 결과는 추정 {signed_loss(rate_before['predicted_loss_pct'])} / 실제 {signed_loss(rate_before['actual_loss_pct'])}입니다. 해당 구간 SPY에서도 {signed_loss(rate_before['spy_proxy_loss_pct'])}이 발생했으므로 순수 금리 충격만 있었던 구간이 아닙니다. TLT 30% 포트폴리오의 결과는 추정 {signed_loss(rate_after['predicted_loss_pct'])} / 실제 {signed_loss(rate_after['actual_loss_pct'])}입니다.
3. **추정 베타의 가치는 단순 비교 기준과 함께 봐야 합니다.** 시장 팩터의 변경 전·후 MAE는 각각 {market_before['mae_pp']:.2f}%p / {market_after['mae_pp']:.2f}%p였습니다. 단순 SPY 대용치의 MAE는 각각 {market_before['spy_proxy_baseline_mae_pp']:.2f}%p / {market_after['spy_proxy_baseline_mae_pp']:.2f}%p입니다. 추정 베타 MAE가 기준보다 큰 경우 추가적인 재현력 개선이 확인된 것이 아닙니다.
4. **평균 구간 오차만으로 꼬리위험 재현력이 검증됐다고 볼 수 없습니다.** 실제 손실 상위 약 10%인 {int(market_before['worst_decile_intervals'])}개 구간의 시장 팩터 MAE는 변경 전 {market_before['worst_decile_mae_pp']:.2f}%p / 변경 후 {market_after['worst_decile_mae_pp']:.2f}%p였고, 평균 실제−추정 차이는 각각 {market_before['worst_decile_mean_underestimate_pp']:+.2f}%p / {market_after['worst_decile_mean_underestimate_pp']:+.2f}%p였습니다. 양수는 평균적인 손실 과소 추정을 뜻합니다.

고정 시나리오의 **민감도 비교 도구**로는 한계를 명시해 사용할 수 있습니다. 실제 총손실 예측이나 최대손실 한도로 제시하는 용도는 추가 검증과 방법 보완이 필요합니다.
이 결과에 맞추기 위한 베타·시나리오·포트폴리오 비중 재조정은 수행하지 않았습니다.

## 세 고정 충격 구간

양수는 손실, 음수는 이익입니다. `실제−추정`이 양수이면 손실을 과소 추정했습니다.

{table}

[비교 차트](stress_validation_comparison.html) · [전체 자산·포트폴리오 결과](stress_validation_event_replay.csv)

{case_table}

2020년 두 사례는 원천 스냅샷이 2018년에 시작하므로 756일보다 짧은 가용 이력을 사용했습니다.
최소 252개의 유효 회귀 표본을 요구했으며, 부족한 기간을 채우거나 0으로 대체하지 않았습니다.
주식·변동성 충격 구간은 서로 겹쳐 독립적인 두 위기 검증으로 해석할 수 없습니다.

{asset_table}

자산별 평균 오차는 이 28개 지원 자산 내 기술통계이며, 시장 전체나 상장폐지 종목을 포함한 모집단 추정이 아닙니다.

## 전체 기간 비교

756개 일간 수익률의 학습창을 확보한 시점부터, 10거래일 간격으로 시작일을 고정했습니다.
각 구간의 베타는 시작일 **전 거래일**까지 추정했습니다. 3년 창의 금리 결측은 해당 회귀에서만 제외합니다.
미래 구간의 수익률·팩터값을 바꿔도 그 구간에 사용한 베타가 바뀌지 않는지 테스트합니다.
마지막 완성 구간 이후 10거래일 미만인 잔여 관측은 제외했으며 시작일 간격을 결과에 맞춰 조정하지 않았습니다.

{summary_table}

MAE는 절대 손실 오차의 평균입니다. 비교 기준은 모든 구간의 손실을 0%로 추정한 경우와 해당 구간 SPY 손실을 그대로 사용한 경우(시장 베타 1 가정)입니다.
두 기준도 실제 구간 평가용이며, SPY 대용치는 미래 SPY 수익률 예측이 아닙니다.
손실 상위 약 10%는 포트폴리오별 실제 손실이 큰 15/145개 구간을 사후 선정한 진단용 부분집합이며, 사전 탐지 성능이 아닙니다.
평상시와 위기 시의 오차를 구분하기 위한 비교이며, 수익률이 0에 가까울 때 불안정한 백분율 오차(MAPE)는 쓰지 않았습니다.
성과 유의성·확률적 손실 보장·신뢰구간은 주장하지 않습니다.

[90개 자산/포트폴리오·팩터별 요약](stress_validation_rolling_summary.csv) · [구간별 원 계산](stress_validation_rolling_replay.csv)

## 방법과 해석

- 학습: 각 자산에 대해 일간 수익률과 SPY 일간 수익률 / DGS10 일간 변화(bp) / VIX 일간 변화(pt)를 하나씩 회귀합니다. 기존 운영 계산 함수를 사용합니다.
- 추정 손실(%): `−100 × Σ(시작 비중 × 사전 베타) × 관측된 10일 팩터 충격`. 회귀 절편은 기존 스트레스 방식과 같이 포함하지 않습니다.
- 실제 손실(%): `−100 × Σ(시작 비중 × (종료 수정종가 / 시작 수정종가 − 1))`. 구간 내 매매 없는 buy-and-hold이며 배당·분할을 반영한 저장 수정종가 기준입니다. 학습의 일간 포트폴리오 민감도는 고정 비중 가중합이므로 실제 구간 내 비중 변화도 잔차에 포함됩니다.
- `before`: AAPL/MSFT 각 30%, NVDA/AMZN 각 20%. `after`: 기존 비중의 70%를 유지하고 TLT 30% 편입. 현재 정한 예시를 과거에 대입한 비교이며 당시 실제 운용 기록이 아닙니다.
- 충격은 반올림 전 실제 구간 변화량을 사용하며, 기존 시나리오 파일의 반올림된 충격도 CSV에 보존했습니다. 기존 파일과 운영 엔진은 변경하지 않았습니다.
- 금리 충격의 수준값만 기존 시나리오 규칙대로 과거 관측을 이월합니다. 일간 금리 회귀의 결측 당일과 다음 날은 제외합니다. 미래값 보간은 없습니다.
- 세 팩터는 별도 단변량 민감도이며 시나리오 손실을 합산하지 않습니다. 실제 총손실에는 동시에 발생한 다른 팩터, 종목 고유 움직임과 비선형성이 포함되어 있으므로, 오차를 모두 베타 불안정성 때문이라고 단정할 수 없습니다.
- 고정 충격은 전체 저장 기간의 극단값으로 사후 선정됐습니다. 결과는 위기 재현 진단이며, 사전에 독립적으로 정한 이벤트의 외부 검증은 아닙니다.
- 28개 현재 지원 자산에 대한 결과로, 상장폐지·과거 구성종목을 포함한 모집단 검증은 아닙니다. 최신 수정종가와 금리 스냅샷을 사용하므로 당시 데이터 공표 시각·개정 이력을 재현한 point-in-time 검증도 아닙니다.
- 10일 결과 구간은 겹치지 않지만 학습 기간은 겹칩니다. 세 위기 구간만으로 일반화하거나 개별 자산·구간 행을 독립 표본으로 합산하지 않습니다.

## 데이터·재현·검사

입력 가격 {manifest['quality']['price_rows']:,}행 × {manifest['quality']['assets']}개 자산, 기간 {manifest['quality']['first_date']}~{manifest['quality']['last_date']}.
가격 결측·비양수·중복 날짜는 없으며, 팩터 날짜는 가격과 정확히 일치합니다.
DGS10 결측은 {manifest['quality']['missing_dgs10']}행으로 유지했습니다. 상세 원천·파일 해시·계산 정의는 [검증 manifest](stress_validation_manifest.json)에 있습니다.

```bash
python -m analysis.portfolio_stress_validation
python -m pytest tests/test_portfolio_stress_validation.py
```

명령은 다운로드·원천 갱신·운영 시나리오 변경 없이 검증 CSV, JSON, 이 문서를 재생성합니다.
차트 HTML은 `stress_validation_comparison.json`을 Data 표준 렌더러에 전달해 생성합니다.

## 검증 범위 기록

아래 분모는 이 Stress 검증에서 정의한 검토 단위 수이며 전체 프로젝트의 검증 비율이 아닙니다.
`0 / N`은 남은 확정 오류를 발견하지 못했다는 뜻이며, 미확인 사항까지 검증 완료했다는 뜻은 아닙니다.

### 결과물 품질

| Category | Observed defects | Assessment |
| --- | --- | --- |
| 질문 충족·완전성 | 0 / 2 | 고정 사례와 전체 비중첩 구간 비교 완료. 시나리오별 추정과 실제를 같은 구간으로 정렬. |
| 분석 명확성 | 0 / 3 | 사례·전체구간·방법에 손실 부호, 표본과 조건부 해석을 명시. |
| 시각·상호작용 | 0 / 1 | 표준 차트 payload 검증 완료. 이 실행환경에 브라우저가 없어 실제 화면·상호작용은 미확인. HTML은 CDN 접근 필요. |

### 수치·분석 타당성

| Category | Observed defects | Assessment |
| --- | --- | --- |
| 원천 권위·신뢰 | 0 / 6 | 입력 6개 파일 해시와 원천 표시 보존. 외부 제공처 재조회·당시 공표본 대조는 범위 밖. |
| 값 정확성 | 0 / 3 | 사례·구간별 결과·집계의 테스트 및 독립 최소제곱 대조. 상세 테스트 기록은 아래 참조. |
| 차트 내부 일치 | 0 / 1 | 차트 JSON의 6개 비교쌍은 사례 CSV와 대조. 실제 픽셀 렌더링은 미확인. |
| 원천·방법 기록 | 0 / 3 | 사례·전체구간·요약에 대응하는 원 CSV, 입력 해시와 방법 기록 제공. |
| 결과물 간 일치 | 0 / 4 | Stress 검증 본문·차트 입력·팩터 베타 분석 연결·README 연결 대조. |
| 데이터 품질 | 0 / 2 | 가격과 팩터의 날짜 중복·정렬·결측·양수 및 정확한 날짜 일치 검사. |
| 결론 지지 | 0 / 4 | 위의 4개 주요 결과를 계산값과 대조. 원인·통계적 유의성·예측 보장 주장은 하지 않음. |

### 우선 문제와 조치

1. **총손실 해석 — 보완 필요:** 단일 팩터 민감도는 동시 충격과 종목 고유 변동을 포함한 총손실을 재현하지 못할 수 있습니다. 실제 손실 예측으로 사용하려면 별도 모델·평가가 필요하며, 이번 검증 결과에 맞춘 운영 모델 수정은 하지 않았습니다.
2. **검증 근거 부재 — 보완 완료:** 사전 베타, 실제 손실, 단순 기준과 꼬리 구간 오차를 재현 가능한 코드·CSV로 추가했습니다. 팩터 베타 분석의 일방적인 과소 추정 가능성 서술도 실제 양방향 오차를 반영하도록 수정했습니다.
3. **표본·원천 한계 — 명시 완료:** 2020년 이력 부족, 사례 중첩, 사후 극단 사례 선택, 현재 자산군과 수정 스냅샷 사용의 한계를 위에 명시했습니다. 추가 자료 없이 이를 해소한 것으로 주장하지 않습니다.

실행 검증·환경 제한의 기록은 [검사 기록](stress_validation_checks.json)을 참조하세요.
"""
    (OUT / "stress_validation_report.md").write_text(report)


def main():
    inputs = [ROOT / "data" / "portfolio" / name for name in
              ("prices.csv", "factors.csv", "scenarios.json", "snapshot_meta.json")]
    inputs += [ROOT / "examples" / "portfolio" / f"{name}.json" for name in ("before", "after")]
    prices = pd.read_csv(inputs[0], index_col="Date", parse_dates=True)
    factors = pd.read_csv(inputs[1], index_col="Date", parse_dates=True)
    scenarios = json.loads(inputs[2].read_text())["scenarios"]
    validate_inputs(prices, factors)
    portfolios = load_portfolios()
    cases = replay_cases(prices, factors, scenarios, portfolios)
    rolling = rolling_replay(prices, factors, portfolios)
    summary = summarize(rolling)
    manifest = {
        "snapshot_as_of": json.loads(inputs[3].read_text())["as_of"],
        "source_metadata": json.loads(inputs[3].read_text()),
        "runtime": {"python": platform.python_version(), "pandas": pd.__version__, "numpy": np.__version__},
        "inputs_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
        "method": {"beta_cutoff": "strictly before interval start", "lookback_returns": WINDOW,
                   "minimum_paired_observations": MIN_OBSERVATIONS, "horizon_observations": HORIZON,
                   "rolling_start_index": WINDOW + 1, "rolling_stride": HORIZON,
                   "actual_portfolio": "initial-weight buy-and-hold adjusted-close total return",
                   "shock": "realized, conditional, not forecast; no rounding",
                   "error": "actual loss minus estimated loss, percentage points",
                   "cases_partial_history": True, "rolling_partial_history": False},
        "quality": {"price_rows": len(prices), "assets": len(prices.columns),
                    "first_date": str(prices.index[0].date()), "last_date": str(prices.index[-1].date()),
                    "missing_dgs10": int(factors["DGS10"].isna().sum()),
                    "missing_prices": 0, "duplicate_dates": 0, "exact_date_alignment": True},
        "coverage": {"case_rows": len(cases), "rolling_rows": len(rolling),
                     "rolling_intervals_per_subject_factor": int(summary["intervals"].iloc[0]),
                     "assets": len(prices.columns), "portfolios": list(portfolios)},
        "limitations": ["ex-post extreme case selection", "overlapping 2020 case windows",
                        "2020 history shorter than 756 returns", "current-universe survivorship",
                        "revised adjusted-close snapshot, not historical release vintages",
                        "single-factor conditional replay is not a total-loss forecast"],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    for name, frame in (("stress_validation_event_replay", cases), ("stress_validation_rolling_replay", rolling), ("stress_validation_rolling_summary", summary)):
        frame.to_csv(OUT / f"{name}.csv", index=False, float_format="%.10g")
    (OUT / "stress_validation_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    (OUT / "stress_validation_comparison.json").write_text(json.dumps(chart_config(cases), indent=2, ensure_ascii=False) + "\n")
    write_report(cases, rolling, summary, manifest)
    print(cases[cases["kind"] == "portfolio"][["scenario", "subject", "predicted_loss_pct", "actual_loss_pct", "underestimate_pp"]].round(3).to_string(index=False))
    print(summary[summary["kind"] == "portfolio"].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
