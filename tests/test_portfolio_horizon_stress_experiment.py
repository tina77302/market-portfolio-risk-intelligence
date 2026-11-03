import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from analysis.portfolio_horizon_stress_experiment import (
    MIN_BLOCKS, fit_direct, gates, replay, training_blocks,
)


@pytest.fixture
def history():
    """Known joint coefficients on non-overlapping 10-day endpoint returns."""
    rng = np.random.default_rng(512)
    n = 811
    days = pd.bdate_range("2018-01-01", periods=n)
    spy = 100 * np.cumprod(1 + rng.normal(0, 0.008, n))
    rate = 3 + np.cumsum(rng.normal(0, 2, n)) / 100
    boundaries = np.arange(0, n, 10)
    market = spy[boundaries[1:]] / spy[boundaries[:-1]] - 1
    rate_moves = (rate[boundaries[1:]] - rate[boundaries[:-1]]) * 100
    stock_nodes = np.r_[100, 100 * np.cumprod(1 + 0.001 + 1.4 * market - 0.0008 * rate_moves)]
    bond_nodes = np.r_[100, 100 * np.cumprod(1 + 0.2 * market - 0.0012 * rate_moves)]
    prices = pd.DataFrame({"SPY": spy,
                           "STOCK": np.exp(np.interp(np.arange(n), boundaries, np.log(stock_nodes))),
                           "BOND": np.exp(np.interp(np.arange(n), boundaries, np.log(bond_nodes)))}, index=days)
    factors = pd.DataFrame({"DGS10": rate, "VIX": 25 + np.cumsum(rng.normal(0, 0.1, n))}, index=days)
    return prices, factors


def test_nonoverlap_training_blocks_end_strictly_before_evaluation(history):
    prices, factors = history
    x, y, blocks = training_blocks(prices, factors, prices.index[781])
    assert len(blocks) == len(x) == len(y) == 75
    assert blocks.block_end.max() == str(prices.index[780].date())
    assert (blocks.block_end < str(prices.index[781].date())).all()
    assert blocks.block_start.iloc[1:].to_list() == blocks.block_end.iloc[:-1].to_list()
    for row in blocks.itertuples():
        assert prices.index.get_loc(row.block_end) - prices.index.get_loc(row.block_start) == 10


def test_known_10day_coefficients_and_intercept_are_recovered(history):
    prices, factors = history
    fitted = fit_direct(prices, factors, prices.index[781])
    np.testing.assert_allclose(fitted["beta"].loc["STOCK"], [1.4, -0.0008], atol=1e-11)
    np.testing.assert_allclose(fitted["beta"].loc["BOND"], [0.2, -0.0012], atol=1e-11)
    assert fitted["intercept"]["STOCK"] == pytest.approx(0.001, abs=1e-12)
    assert fitted["intercept"]["BOND"] == pytest.approx(0, abs=1e-12)


def test_start_and_future_outcomes_do_not_change_any_training_inputs(history):
    prices, factors = history
    start, end = prices.index[[781, 791]]
    original, old_blocks = replay(prices, factors, start, end, {})
    new_prices, new_factors = prices.copy(), factors.copy()
    new_prices.loc[start:, "STOCK"] *= np.linspace(1.5, 2, len(prices.loc[start:]))
    new_factors.loc[start:, "DGS10"] += np.linspace(1, 3, len(prices.loc[start:]))
    changed, new_blocks = replay(new_prices, new_factors, start, end, {})
    pd.testing.assert_frame_equal(old_blocks, new_blocks)
    for field in ("beta_market", "beta_rate", "fitted_intercept", "paired_observations"):
        np.testing.assert_allclose(original[field], changed[field], equal_nan=True)
    assert not np.allclose(original.actual_loss_pct, changed.actual_loss_pct)


def test_missing_rate_endpoints_remove_blocks_but_interior_gaps_do_not(history):
    prices, factors = history
    endpoint_gap = factors.copy()
    endpoint_gap.loc[prices.index[400], "DGS10"] = np.nan
    fitted = fit_direct(prices, endpoint_gap, prices.index[781])
    assert fitted["n"] == 73
    assert not fitted["blocks"].loc[fitted["blocks"].block_end == str(prices.index[400].date()), "used_in_fit"].item()
    interior_gap = factors.copy()
    interior_gap.loc[prices.index[401], "DGS10"] = np.nan
    assert fit_direct(prices, interior_gap, prices.index[781])["n"] == 75


def test_intercept_controls_and_weighted_contributions_reconcile(history):
    prices, factors = history
    rows, _ = replay(prices, factors, prices.index[781], prices.index[791], {"mix": {"STOCK": 0.7, "BOND": 0.3}})
    fitted = rows[rows.model.str.startswith(("daily", "direct"))]
    np.testing.assert_allclose(fitted.predicted_loss_pct, fitted[["contribution_market_pct", "contribution_rate_pct", "contribution_intercept_pct"]].sum(axis=1))
    for model in ("direct_10d_joint", "direct_10d_sensitivity", "daily_joint", "daily_joint_with_intercept"):
        group = rows[rows.model == model].set_index("subject")
        for field in ("actual_loss_pct", "predicted_loss_pct", "beta_market", "beta_rate"):
            assert group.at["mix", field] == pytest.approx(0.7 * group.at["STOCK", field] + 0.3 * group.at["BOND", field])
    group = rows[rows.subject == "STOCK"].set_index("model")
    assert group.at["direct_10d_joint", "predicted_loss_pct"] - group.at["direct_10d_sensitivity", "predicted_loss_pct"] == pytest.approx(-0.1)
    assert group.at["daily_joint_with_intercept", "contribution_intercept_pct"] == pytest.approx(-1000 * group.at["daily_joint_with_intercept", "fitted_intercept"])


def test_incomplete_lookback_and_invalid_horizon_fail(history):
    prices, factors = history
    with pytest.raises(ValueError, match="not enough complete"):
        training_blocks(prices, factors, prices.index[200])
    with pytest.raises(ValueError, match="exactly 10"):
        replay(prices, factors, prices.index[781], prices.index[790], {})
    # At least 25 usable complete blocks are required after excluding endpoints.
    gaps = factors.copy()
    gaps.loc[prices.index[::10], "DGS10"] = np.nan
    with pytest.raises(ValueError, match="insufficient"):
        fit_direct(prices, gaps, prices.index[781])


def test_all_saved_results_match_independent_unscaled_covariance_solution():
    root = Path(__file__).resolve().parents[1]
    out = root / "reports/portfolio/direct_10d_stress"
    prices = pd.read_csv(root / "data/portfolio/prices.csv", index_col="Date", parse_dates=True)
    factors = pd.read_csv(root / "data/portfolio/factors.csv", index_col="Date", parse_dates=True)
    weights = {t: {t: 1.0} for t in prices.columns}
    for subject in ("before", "after"):
        request = json.loads((root / f"examples/portfolio/{subject}.json").read_text())
        weights[subject] = {h["ticker"]: h["weight"] / 100 for h in request["holdings"]}
    rows = pd.concat([pd.read_csv(out / f"stress_validation_{name}.csv") for name in ("cases", "rolling")])
    for (start, end), group in rows.groupby(["start", "end"]):
        pos = prices.index.get_loc(start)
        oldest, last = max(0, pos - 757), pos - 1
        end_positions = list(reversed(list(range(last, oldest + 9, -10))))
        xs, ys = [], []
        for stop in end_positions:
            begin = stop - 10
            x = [prices.iloc[stop]["SPY"] / prices.iloc[begin]["SPY"] - 1,
                 100 * (factors.iloc[stop]["DGS10"] - factors.iloc[begin]["DGS10"])]
            if np.isfinite(x).all():
                xs.append(x)
                ys.append(prices.iloc[stop].to_numpy() / prices.iloc[begin].to_numpy() - 1)
        x, y = np.array(xs), np.array(ys)
        xc, yc = x - x.mean(axis=0), y - y.mean(axis=0)
        beta = np.linalg.solve(xc.T @ xc, xc.T @ yc)
        intercept = y.mean(axis=0) - x.mean(axis=0) @ beta
        daily_prices = prices.iloc[oldest:pos]
        daily_factors = factors.loc[daily_prices.index]
        daily_y = daily_prices.to_numpy()[1:] / daily_prices.to_numpy()[:-1] - 1
        daily_x = np.column_stack([daily_y[:, prices.columns.get_loc("SPY")], np.diff(daily_factors.DGS10) * 100])
        valid = np.isfinite(daily_x).all(axis=1)
        dx, dy = daily_x[valid], daily_y[valid]
        dxc, dyc = dx - dx.mean(axis=0), dy - dy.mean(axis=0)
        daily_beta = np.linalg.solve(dxc.T @ dxc, dxc.T @ dyc)
        daily_intercept = dy.mean(axis=0) - dx.mean(axis=0) @ daily_beta
        shocks = np.array([prices.loc[end, "SPY"] / prices.loc[start, "SPY"] - 1,
                           100 * (factors.DGS10.ffill().loc[end] - factors.DGS10.ffill().loc[start])])
        actual_returns = prices.loc[end].to_numpy() / prices.loc[start].to_numpy() - 1
        for row in group.itertuples():
            w = np.array([weights[row.subject].get(t, 0) for t in prices.columns])
            if row.model == "spy_proxy":
                expected = -100 * shocks[0]
            elif row.model == "zero_loss":
                expected = 0
            else:
                if row.model.startswith("direct"):
                    coefs = beta @ w
                    drift = w @ intercept if row.model == "direct_10d_joint" else 0
                    assert row.paired_observations == len(x) >= MIN_BLOCKS
                else:
                    coefs = daily_beta @ w
                    drift = 10 * (w @ daily_intercept) if row.model == "daily_joint_with_intercept" else 0
                    assert row.paired_observations == valid.sum()
                expected = -100 * (coefs @ shocks + drift)
                assert row.train_end < start
                assert row.beta_market == pytest.approx(coefs[0], abs=1e-8)
                assert row.beta_rate == pytest.approx(coefs[1], abs=1e-8)
                assert row.contribution_market_pct == pytest.approx(-100 * coefs[0] * shocks[0], abs=1e-7)
                assert row.contribution_rate_pct == pytest.approx(-100 * coefs[1] * shocks[1], abs=1e-7)
                assert row.contribution_intercept_pct == pytest.approx(-100 * drift, abs=1e-7)
            assert row.predicted_loss_pct == pytest.approx(expected, abs=1e-7)
            assert row.actual_loss_pct == pytest.approx(-100 * (w @ actual_returns), abs=1e-7)
            assert row.underestimate_pp == pytest.approx(-100 * (w @ actual_returns) - expected, abs=1e-7)


def test_first_revision_rows_and_daily_intercept_control_match_preserved_outputs():
    root = Path(__file__).resolve().parents[1] / "reports/portfolio"
    old = pd.read_csv(root / "joint_stress/rolling.csv")
    old = old[old.model == "joint_market_rate"]
    new = pd.read_csv(root / "direct_10d_stress/stress_validation_rolling.csv")
    for name, include_drift in (("daily_joint", False), ("daily_joint_with_intercept", True)):
        joined = old.merge(new[new.model == name], on=["subject", "start", "end"], suffixes=("_old", "_new"), validate="one_to_one")
        assert len(joined) == 145 * 30
        expected = joined.predicted_loss_pct_old - (1000 * joined.fitted_daily_intercept if include_drift else 0)
        np.testing.assert_allclose(joined.predicted_loss_pct_new, expected, atol=1e-7)


def test_saved_blocks_metrics_gates_and_chart_are_consistent():
    out = Path(__file__).resolve().parents[1] / "reports/portfolio/direct_10d_stress"
    rows = pd.read_csv(out / "stress_validation_rolling.csv")
    blocks = pd.read_csv(out / "stress_validation_training_blocks.csv")
    summary = pd.read_csv(out / "stress_validation_summary.csv")
    assert len(rows) == 145 * 30 * 6
    assert not rows[["subject", "model", "start", "end"]].duplicated().any()
    assert blocks.block_end.lt(blocks.evaluation_start).all()
    for _, values in blocks.groupby("evaluation_start"):
        assert values.block_start.iloc[1:].to_list() == values.block_end.iloc[:-1].to_list()
        assert values.used_in_fit.sum() >= MIN_BLOCKS
    for metric in summary.itertuples():
        values = rows[(rows.subject == metric.subject) & (rows.model == metric.model)]
        assert len(values) == metric.intervals == 145
        assert metric.mae_pp == pytest.approx((values.actual_loss_pct - values.predicted_loss_pct).abs().mean(), abs=1e-7)
        tail = values.nlargest(15, "actual_loss_pct")
        assert metric.tail_mean_positive_underestimate_pp == pytest.approx(tail.underestimate_pp.clip(lower=0).mean(), abs=1e-7)
    expected_gates = gates(summary)
    pd.testing.assert_frame_equal(pd.read_csv(out / "stress_validation_gates.csv"), expected_gates)
    chart = json.loads((out / "stress_validation_comparison.json").read_text())
    for point, model in zip(chart["rows"], ("daily_joint", "direct_10d_joint", "direct_10d_sensitivity", "spy_proxy")):
        group = summary[summary.model == model].set_index("subject")
        assert point["변경 전"] == pytest.approx(group.at["before", "mae_pp"], abs=1e-9)
        assert point["TLT 30%"] == pytest.approx(group.at["after", "mae_pp"], abs=1e-9)


def test_preserved_input_and_first_revision_artifact_hashes():
    root = Path(__file__).resolve().parents[1]
    reports = root / "reports/portfolio"
    manifest = json.loads((reports / "direct_10d_stress/stress_validation_manifest.json").read_text())
    for name, digest in manifest["inputs_sha256"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
    previous = json.loads((reports / "joint_stress/checks.json").read_text())
    for name, digest in previous["output_sha256"].items():
        assert hashlib.sha256((reports / "joint_stress" / name).read_bytes()).hexdigest() == digest
