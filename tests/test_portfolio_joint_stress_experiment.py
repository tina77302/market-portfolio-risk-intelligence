import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from analysis.portfolio_joint_stress_experiment import (
    MODEL_FACTORS, adoption_checks, fit_before, fit_ols, replay, summarize,
)


@pytest.fixture
def history():
    rng = np.random.default_rng(421)
    n = 800
    days = pd.bdate_range("2018-01-01", periods=n)
    market = rng.normal(0, 0.008, n)
    rate = 150 * market + rng.normal(0, 2, n)
    vol = -30 * market + rng.normal(0, 0.2, n)
    stock = 0.0002 + 1.3 * market - 0.0007 * rate - 0.002 * vol
    bond = -0.001 * rate + 0.1 * market
    prices = pd.DataFrame({"SPY": 100 * np.cumprod(1 + market),
                           "STOCK": 100 * np.cumprod(1 + stock),
                           "BOND": 100 * np.cumprod(1 + bond)}, index=days)
    factors = pd.DataFrame({"DGS10": 3 + np.cumsum(rate) / 100,
                            "VIX": 30 + np.cumsum(vol)}, index=days)
    return prices, factors


def test_joint_fit_recovers_known_coefficients_in_original_units(history):
    prices, factors = history
    fit = fit_before(prices, factors, prices.index[780])["joint_market_rate_vix"]
    assert fit["beta"].loc["STOCK"].to_numpy() == pytest.approx([1.3, -0.0007, -0.002], abs=1e-11)
    assert fit["intercept"]["STOCK"] == pytest.approx(0.0002, abs=1e-12)
    assert fit["beta"].loc["BOND"].to_numpy() == pytest.approx([0.1, -0.001, 0], abs=1e-11)
    assert fit["n"] == 756


def test_joint_betas_do_not_use_interval_or_future_data(history):
    prices, factors = history
    start, end = prices.index[[780, 790]]
    original = replay(prices, factors, start, end, {})
    changed_prices, changed_factors = prices.copy(), factors.copy()
    changed_prices.loc[start:, "STOCK"] *= np.linspace(1.5, 3, len(prices.loc[start:]))
    changed_factors.loc[start:, "DGS10"] += 2
    changed_factors.loc[start:, "VIX"] += np.arange(len(prices.loc[start:]))
    changed = replay(changed_prices, changed_factors, start, end, {})
    for field in ["beta_market", "beta_rate", "beta_volatility", "fitted_daily_intercept"]:
        np.testing.assert_allclose(original[field], changed[field], equal_nan=True)
    assert original.loc[original.model.isin(MODEL_FACTORS), "train_end"].lt(str(start.date())).all()
    assert not np.allclose(original.actual_loss_pct, changed.actual_loss_pct)


def test_rate_missingness_has_a_matched_control_without_forward_filling(history):
    prices, factors = history
    factors.loc[prices.index[400], "DGS10"] = np.nan
    fitted = fit_before(prices, factors, prices.index[780])
    assert fitted["legacy_market"]["n"] == fitted["legacy_volatility"]["n"] == 756
    for model in ("legacy_rate", "matched_market", "joint_market_rate", "joint_market_rate_vix"):
        assert fitted[model]["n"] == 754
    assert fitted["joint_market_rate_vix"]["beta"].loc["STOCK", "rate"] == pytest.approx(-0.0007)


def test_joint_contributions_and_portfolio_weights_reconcile(history):
    prices, factors = history
    result = replay(prices, factors, prices.index[780], prices.index[790], {"mix": {"STOCK": 0.7, "BOND": 0.3}})
    fitted = result[result.model.isin(MODEL_FACTORS)]
    np.testing.assert_allclose(fitted.predicted_loss_pct,
                              fitted[[f"contribution_{f}_pct" for f in ("market", "rate", "volatility")]].sum(axis=1))
    joint = result[result.model == "joint_market_rate_vix"].set_index("subject")
    for field in ["beta_market", "beta_rate", "beta_volatility", "predicted_loss_pct", "actual_loss_pct"]:
        assert joint.at["mix", field] == pytest.approx(0.7 * joint.at["STOCK", field] + 0.3 * joint.at["BOND", field])
    legacy = result[result.model == "legacy_rate"]
    assert legacy.beta_market.eq(0).all() and legacy.beta_volatility.eq(0).all()


def test_constant_or_collinear_factors_and_insufficient_data_fail_explicitly():
    x = np.arange(300, dtype=float)[:, None]
    y = (2 * x + 1)
    with pytest.raises(ValueError, match="constant"):
        fit_ols(np.ones((300, 1)), y)
    with pytest.raises(ValueError, match="rank-deficient"):
        fit_ols(np.column_stack([x, x]), y)
    with pytest.raises(ValueError, match="insufficient"):
        fit_ols(x[:50], y[:50])


def test_gate_checks_each_portfolio_and_does_not_offset_tail_underestimates():
    rows = []
    for subject in ("before", "after"):
        for model, mae, tail in [("legacy_market", 2, 3), ("spy_proxy", 1.5, 2),
                                 ("joint_market_rate", 1.4, 4), ("joint_market_rate_vix", 1.4, 2)]:
            rows.append({"subject": subject, "kind": "portfolio", "model": model,
                         "mae_pp": mae, "tail_mean_positive_underestimate_pp": tail})
    gates = adoption_checks(pd.DataFrame(rows)).set_index(["subject", "model"])
    assert not gates.loc[("before", "joint_market_rate"), "passes_all_descriptive_gates"]
    assert gates.loc[("after", "joint_market_rate_vix"), "passes_all_descriptive_gates"]
    values = pd.DataFrame({"subject": ["p"] * 20, "kind": ["portfolio"] * 20,
                           "model": ["m"] * 20, "actual_loss_pct": list(range(20)),
                           "underestimate_pp": [0] * 18 + [5, -5], "absolute_error_pp": [0] * 18 + [5, 5]})
    row = summarize(values).iloc[0]
    assert row.tail_mean_underestimate_pp == 0
    assert row.tail_mean_positive_underestimate_pp == 2.5


def test_saved_results_match_independent_unscaled_centered_normal_equations():
    """Independently verify all assets, portfolios, dates, models and sums."""
    root = Path(__file__).resolve().parents[1]
    out = root / "reports/portfolio/joint_stress"
    prices = pd.read_csv(root / "data/portfolio/prices.csv", index_col="Date", parse_dates=True)
    factors = pd.read_csv(root / "data/portfolio/factors.csv", index_col="Date", parse_dates=True)
    rows = pd.concat([pd.read_csv(out / f"{name}.csv") for name in ("cases", "rolling")], ignore_index=True)
    weights = {t: {t: 1.0} for t in prices.columns}
    for name in ("before", "after"):
        data = json.loads((root / f"examples/portfolio/{name}.json").read_text())
        weights[name] = {h["ticker"]: h["weight"] / 100 for h in data["holdings"]}
    for (start, end), group in rows.groupby(["start", "end"]):
        pos = prices.index.get_loc(start)
        pp = prices.iloc[max(0, pos - 757):pos]
        ff = factors.loc[pp.index]
        y = pp.to_numpy()[1:] / pp.to_numpy()[:-1] - 1
        x = np.column_stack([y[:, prices.columns.get_loc("SPY")],
                             np.diff(ff.DGS10) * 100, np.diff(ff.VIX)])
        complete = np.isfinite(x).all(axis=1)
        shocks = np.array([prices.loc[end, "SPY"] / prices.loc[start, "SPY"] - 1,
                           (factors.DGS10.ffill().loc[end] - factors.DGS10.ffill().loc[start]) * 100,
                           factors.loc[end, "VIX"] - factors.loc[start, "VIX"]])
        actual = prices.loc[end].to_numpy() / prices.loc[start].to_numpy() - 1
        for model, sub in group.groupby("model"):
            if model in MODEL_FACTORS:
                fields = [dict(market=0, rate=1, volatility=2)[f] for f in MODEL_FACTORS[model]]
                mask = complete if model.startswith("joint_") or model == "matched_market" else np.isfinite(x[:, fields]).all(axis=1)
                xx, yy = x[mask][:, fields], y[mask]
                xc, yc = xx - xx.mean(axis=0), yy - yy.mean(axis=0)
                beta = np.linalg.solve(xc.T @ xc, xc.T @ yc)
                intercept = yy.mean(axis=0) - xx.mean(axis=0) @ beta
            for row in sub.itertuples():
                w = np.array([weights[row.subject].get(t, 0) for t in prices.columns])
                truth = -100 * (w @ actual)
                if model == "spy_proxy":
                    expected = -100 * shocks[0]
                elif model == "zero_loss":
                    expected = 0.0
                else:
                    coefs = beta @ w
                    expected = -100 * (coefs @ shocks[fields])
                    assert row.paired_observations == mask.sum()
                    assert row.fitted_daily_intercept == pytest.approx(w @ intercept, abs=1e-10)
                    for f, index in dict(market=0, rate=1, volatility=2).items():
                        b = coefs[fields.index(index)] if index in fields else 0
                        assert getattr(row, f"beta_{f}") == pytest.approx(b, abs=1e-8)
                        assert getattr(row, f"contribution_{f}_pct") == pytest.approx(-100 * b * shocks[index], abs=1e-7)
                    assert row.train_end < start
                assert row.actual_loss_pct == pytest.approx(truth, abs=1e-7)
                assert row.predicted_loss_pct == pytest.approx(expected, abs=1e-7)
                assert row.underestimate_pp == pytest.approx(truth - expected, abs=1e-7)


def test_existing_stress_validation_single_factor_results_are_preserved():
    root = Path(__file__).resolve().parents[1] / "reports/portfolio"
    old = pd.read_csv(root / "stress_validation_rolling_replay.csv")
    new = pd.read_csv(root / "joint_stress/rolling.csv")
    old["model"] = "legacy_" + old.factor
    joined = old.merge(new, on=["subject", "model", "start", "end"], validate="one_to_one", suffixes=("_old", "_new"))
    assert len(joined) == len(old) == 13050
    for field in ("predicted_loss_pct", "actual_loss_pct"):
        np.testing.assert_allclose(joined[f"{field}_old"], joined[f"{field}_new"], atol=1e-7)


def test_saved_summaries_share_dates_and_tail_membership():
    out = Path(__file__).resolve().parents[1] / "reports/portfolio/joint_stress"
    rows, summary = pd.read_csv(out / "rolling.csv"), pd.read_csv(out / "summary.csv")
    assert len(rows) == 145 * 30 * 8
    assert not rows[["subject", "model", "start", "end"]].duplicated().any()
    for row in summary.itertuples():
        group = rows[(rows.subject == row.subject) & (rows.model == row.model)]
        tail = group.nlargest(15, "actual_loss_pct")
        assert row.intervals == len(group) == 145
        assert row.mae_pp == pytest.approx((group.actual_loss_pct - group.predicted_loss_pct).abs().mean(), abs=1e-7)
        assert row.tail_mean_positive_underestimate_pp == pytest.approx(tail.underestimate_pp.clip(lower=0).mean(), abs=1e-7)
    truth = rows.pivot(index=["subject", "start", "end"], columns="model", values="actual_loss_pct")
    assert truth.notna().all().all()
    assert np.allclose(truth.max(axis=1), truth.min(axis=1))


def test_recorded_gates_and_chart_match_saved_summaries():
    out = Path(__file__).resolve().parents[1] / "reports/portfolio/joint_stress"
    summary = pd.read_csv(out / "summary.csv")
    gates = pd.read_csv(out / "gates.csv")
    chart = json.loads((out / "comparison.json").read_text())
    assert len(gates) == 4
    for row in gates.itertuples():
        selected = summary[(summary.subject == row.subject) & (summary.kind == "portfolio")].set_index("model")
        candidate = selected.loc[row.model]
        checks = (
            candidate.mae_pp < selected.at["legacy_market", "mae_pp"],
            candidate.mae_pp < selected.at["spy_proxy", "mae_pp"],
            candidate.tail_mean_positive_underestimate_pp <= selected.at["legacy_market", "tail_mean_positive_underestimate_pp"],
        )
        assert row.passes_all_descriptive_gates == all(checks)
    for point, model in zip(chart["rows"], ["legacy_market", "joint_market_rate", "joint_market_rate_vix", "spy_proxy"]):
        selected = summary[summary.model == model].set_index("subject")
        assert point["변경 전"] == pytest.approx(selected.at["before", "mae_pp"], abs=1e-9)
        assert point["TLT 30%"] == pytest.approx(selected.at["after", "mae_pp"], abs=1e-9)


def test_source_inputs_and_original_stress_validation_outputs_have_not_changed():
    root = Path(__file__).resolve().parents[1]
    out = root / "reports/portfolio"
    manifest = json.loads((out / "joint_stress/manifest.json").read_text())
    for name, digest in manifest["inputs_sha256"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
    original = json.loads((out / "stress_validation_checks.json").read_text())
    for name, digest in original["artifact_sha256"].items():
        assert hashlib.sha256((out / name).read_bytes()).hexdigest() == digest
