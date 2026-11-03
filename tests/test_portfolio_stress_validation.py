import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from analysis.portfolio_stress_validation import (
    replay_interval,
    rolling_replay,
    summarize,
    validate_inputs,
)


@pytest.fixture
def history():
    rng = np.random.default_rng(45)
    days = pd.bdate_range("2018-01-01", periods=800)
    market = rng.normal(0.0002, 0.012, len(days))
    rate_bp = rng.normal(0, 3, len(days))
    prices = pd.DataFrame({
        "SPY": 100 * np.cumprod(1 + market),
        "LEV": 100 * np.cumprod(1 + 1.5 * market),
        "BOND": 100 * np.cumprod(1 - 0.001 * rate_bp),
    }, index=days)
    factors = pd.DataFrame({
        "VIX": 20 + np.cumsum(rng.normal(0, 0.1, len(days))),
        "DGS10": 3 + np.cumsum(rate_bp) / 100,
    }, index=days)
    return prices, factors


def test_beta_uses_only_dates_strictly_before_interval(history):
    prices, factors = history
    start, end = prices.index[[780, 790]]
    original = replay_interval(prices, factors, start, end, "market", {})
    changed_prices, changed_factors = prices.copy(), factors.copy()
    changed_prices.loc[start:, "LEV"] *= np.linspace(2, 5, len(prices.loc[start:]))
    changed_prices.loc[start:, "SPY"] *= np.linspace(1, 1.5, len(prices.loc[start:]))
    changed_factors.loc[start:, "VIX"] += 100
    changed = replay_interval(changed_prices, changed_factors, start, end, "market", {})
    np.testing.assert_array_equal(original["beta"], changed["beta"])
    assert original["train_end"].eq(str(prices.index[779].date())).all()
    assert original["training_returns"].eq(756).all()
    assert not np.allclose(original["actual_loss_pct"], changed["actual_loss_pct"])


def test_known_betas_and_buy_hold_loss_match_independent_ols(history):
    prices, factors = history
    start, end = prices.index[[780, 790]]
    row = replay_interval(prices, factors, start, end, "market",
                          {"mix": {"LEV": 0.6, "BOND": 0.4}}).set_index("subject").loc["mix"]
    # Direct least squares on explicitly selected pre-start daily observations.
    daily = prices.iloc[23:780].pct_change(fill_method=None).iloc[1:]
    x = np.column_stack([np.ones(756), daily["SPY"]])
    y = daily["LEV"] * 0.6 + daily["BOND"] * 0.4
    expected_beta = np.linalg.lstsq(x, y, rcond=None)[0][1]
    endpoint_return = sum(w * (prices.at[end, t] / prices.at[start, t] - 1)
                          for t, w in {"LEV": 0.6, "BOND": 0.4}.items())
    assert row["beta"] == pytest.approx(expected_beta)
    assert row["actual_loss_pct"] == pytest.approx(-100 * endpoint_return)
    assert row["underestimate_pp"] == pytest.approx(row["actual_loss_pct"] - row["predicted_loss_pct"])
    assert row["absolute_error_pp"] == pytest.approx(abs(row["underestimate_pp"]))


def test_perfect_spy_market_sensitivity_reproduces_endpoint_loss(history):
    prices, factors = history
    result = replay_interval(prices, factors, prices.index[780], prices.index[790], "market", {})
    row = result.set_index("subject").loc["SPY"]
    assert row["beta"] == pytest.approx(1)
    assert row["predicted_loss_pct"] == pytest.approx(row["actual_loss_pct"], abs=1e-12)


def test_missing_rate_levels_drop_two_training_changes_and_preserve_bp_units(history):
    prices, factors = history
    factors.loc[prices.index[400], "DGS10"] = np.nan
    result = replay_interval(prices, factors, prices.index[780], prices.index[790], "rate", {})
    row = result.set_index("subject").loc["BOND"]
    assert row["paired_observations"] == 754
    assert row["beta"] == pytest.approx(-0.001, abs=1e-12)
    shock = 100 * (factors.iloc[790]["DGS10"] - factors.iloc[780]["DGS10"])
    assert row["realized_shock"] == pytest.approx(shock)
    assert row["predicted_loss_pct"] == pytest.approx(0.1 * shock)


def test_partial_case_history_is_flagged_and_insufficient_history_is_rejected(history):
    prices, factors = history
    result = replay_interval(prices, factors, prices.index[400], prices.index[410], "market", {})
    assert result["training_returns"].eq(399).all()
    assert not result["full_756_window"].any()
    with pytest.raises(ValueError, match="not enough pre-event returns"):
        replay_interval(prices, factors, prices.index[100], prices.index[110], "market", {})


def test_future_rate_missingness_does_not_reduce_training_samples(history):
    prices, factors = history
    factors.loc[prices.index[785], "DGS10"] = np.nan
    result = replay_interval(prices, factors, prices.index[780], prices.index[790], "rate", {})
    assert result["paired_observations"].eq(756).all()


def test_validation_windows_are_full_length_and_outcomes_do_not_overlap(history):
    prices, factors = history
    result = rolling_replay(prices, factors, {})
    windows = result[["start", "end"]].drop_duplicates().reset_index(drop=True)
    assert len(windows) == 4
    assert result["full_756_window"].all()
    assert (result["train_end"] < result["start"]).all()
    for i in range(1, len(windows)):
        assert windows.at[i, "start"] == windows.at[i - 1, "end"]


def test_invalid_source_alignment_and_duplicate_dates_fail(history):
    prices, factors = history
    validate_inputs(prices, factors)
    with pytest.raises(ValueError, match="aligned"):
        validate_inputs(prices.iloc[:-1], factors)
    with pytest.raises(ValueError, match="unique"):
        validate_inputs(pd.concat([prices, prices.iloc[-1:]]), factors)


def test_wrong_horizon_and_invalid_weights_fail(history):
    prices, factors = history
    with pytest.raises(ValueError, match="exactly 10"):
        replay_interval(prices, factors, prices.index[780], prices.index[789], "market", {})
    with pytest.raises(ValueError, match="weights"):
        replay_interval(prices, factors, prices.index[780], prices.index[790], "market",
                        {"bad": {"LEV": 0.7, "BOND": 0.4}})


def test_summary_does_not_confuse_signed_bias_with_absolute_error():
    data = pd.DataFrame({
        "subject": ["p", "p"], "kind": ["portfolio", "portfolio"], "factor": ["market", "market"],
        "actual_loss_pct": [10.0, -4.0], "predicted_loss_pct": [7.0, -1.0],
        "spy_proxy_loss_pct": [8.0, -2.0],
        "underestimate_pp": [3.0, -3.0], "absolute_error_pp": [3.0, 3.0],
    })
    row = summarize(data).iloc[0]
    assert row["mae_pp"] == 3
    assert row["mean_underestimate_pp"] == 0
    assert row["zero_loss_baseline_mae_pp"] == 7
    assert row["spy_proxy_baseline_mae_pp"] == 2
    assert row["actual_loss_intervals"] == 1
    assert row["loss_underestimate_fraction"] == 1
    assert row["worst_decile_mean_underestimate_pp"] == 3


def test_saved_replays_match_independent_least_squares_on_snapshot():
    """Recheck every saved row without production beta or replay helpers."""
    root = Path(__file__).resolve().parents[1]
    prices = pd.read_csv(root / "data/portfolio/prices.csv", index_col="Date", parse_dates=True)
    factors = pd.read_csv(root / "data/portfolio/factors.csv", index_col="Date", parse_dates=True)
    reports = root / "reports/portfolio"
    result = pd.concat([pd.read_csv(reports / f"stress_validation_{name}.csv")
                        for name in ("event_replay", "rolling_replay")], ignore_index=True)
    subjects = {t: {t: 1.0} for t in prices.columns}
    for name in ("before", "after"):
        request = json.loads((root / f"examples/portfolio/{name}.json").read_text())
        subjects[name] = {h["ticker"]: h["weight"] / 100 for h in request["holdings"]}
    for (start, end, factor), group in result.groupby(["start", "end", "factor"]):
        t0, t1 = prices.index.get_loc(start), prices.index.get_loc(end)
        assert t1 - t0 == 10
        # 757 price observations strictly before t0 -> at most 756 daily returns.
        train = prices.iloc[max(0, t0 - 757):t0]
        y = train.to_numpy()[1:] / train.to_numpy()[:-1] - 1
        if factor == "market":
            x = y[:, prices.columns.get_loc("SPY")]
            shock = prices.at[pd.Timestamp(end), "SPY"] / prices.at[pd.Timestamp(start), "SPY"] - 1
        else:
            series = "DGS10" if factor == "rate" else "VIX"
            unit = 100 if factor == "rate" else 1
            x = np.diff(factors.loc[train.index, series].to_numpy()) * unit
            level = factors[series].ffill() if factor == "rate" else factors[series]
            shock = (level.loc[end] - level.loc[start]) * unit
        valid = np.isfinite(x)
        design = np.column_stack([np.ones(valid.sum()), x[valid]])
        beta = np.linalg.lstsq(design, y[valid], rcond=None)[0][1]
        endpoints = prices.loc[end].to_numpy() / prices.loc[start].to_numpy() - 1
        for row in group.itertuples():
            w = np.array([subjects[row.subject].get(t, 0) for t in prices.columns])
            expected = -100 * np.dot(w, beta) * shock
            actual = -100 * np.dot(w, endpoints)
            assert row.beta == pytest.approx(np.dot(w, beta), abs=1e-8)
            assert row.predicted_loss_pct == pytest.approx(expected, abs=1e-7)
            assert row.actual_loss_pct == pytest.approx(actual, abs=1e-7)
            assert row.underestimate_pp == pytest.approx(actual - expected, abs=1e-7)
            assert row.train_end < start
            assert row.paired_observations == valid.sum()


def test_saved_summary_matches_each_subject_factor_without_pooling():
    reports = Path(__file__).resolve().parents[1] / "reports/portfolio"
    rows = pd.read_csv(reports / "stress_validation_rolling_replay.csv")
    summary = pd.read_csv(reports / "stress_validation_rolling_summary.csv")
    for row in summary.itertuples():
        values = rows[(rows.subject == row.subject) & (rows.factor == row.factor)]
        difference = values.actual_loss_pct - values.predicted_loss_pct
        assert len(values) == row.intervals == 145
        assert row.mae_pp == pytest.approx(difference.abs().mean(), abs=1e-7)
        assert row.rmse_pp == pytest.approx(np.sqrt((difference ** 2).mean()), abs=1e-7)
        assert row.mean_underestimate_pp == pytest.approx(difference.mean(), abs=1e-7)
        assert not values[["start", "end"]].duplicated().any()


def test_chart_values_are_the_same_six_comparisons_as_case_csv():
    reports = Path(__file__).resolve().parents[1] / "reports/portfolio"
    cases = pd.read_csv(reports / "stress_validation_event_replay.csv")
    portfolios = cases[cases.kind == "portfolio"].reset_index(drop=True)
    chart = json.loads((reports / "stress_validation_comparison.json").read_text())
    assert len(chart["rows"]) == len(portfolios) == 6
    for index, point in enumerate(chart["rows"]):
        assert point["추정 손실"] == pytest.approx(portfolios.at[index, "predicted_loss_pct"], abs=1e-7)
        assert point["실제 손실"] == pytest.approx(portfolios.at[index, "actual_loss_pct"], abs=1e-7)
