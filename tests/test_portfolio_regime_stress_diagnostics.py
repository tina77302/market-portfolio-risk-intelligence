import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from analysis.portfolio_regime_stress_diagnostics import (
    FOCAL, MODELS, REGIMES, classify, prepare_rows, summarize,
)


@pytest.fixture
def small_source():
    days = pd.bdate_range("2024-01-01", periods=41)
    rows = []
    for i, (market, rate, actual, predicted) in enumerate([
        (-0.05, 20, 10, 8), (-0.08, 10, 15, 18), (0.01, 30, 1, -1), (0.02, 1, -2, -3)
    ]):
        for model in MODELS:
            rows.append({"subject": "p", "kind": "portfolio", "model": model,
                         "start": str(days[10*i].date()), "end": str(days[10*i+10].date()),
                         "actual_loss_pct": actual, "predicted_loss_pct": predicted,
                         "shock_market": market, "shock_rate": rate, "shock_volatility": 0.0})
    return pd.DataFrame(rows)


def test_threshold_boundaries_are_exhaustive_and_mutually_exclusive():
    result = classify([-0.05, -0.05, -0.049999, 0.03, -0.08], [20, 19.9999, 20, -30, 30])
    assert result.tolist() == ["joint_shock", "equity_down", "rate_up", "neither", "joint_shock"]
    with pytest.raises(ValueError, match="finite"):
        classify([np.nan], [20])
    with pytest.raises(ValueError, match="negative"):
        classify([0], [0], equity_cutoff=0.05)


def test_loss_only_underestimate_is_distinct_from_foregone_gain(small_source):
    rows, intervals = prepare_rows(small_source)
    summary = summarize(rows, "regime", REGIMES)
    focal = summary[summary.model == FOCAL].set_index("regime")
    assert intervals.regime.to_list() == list(REGIMES)
    assert focal.at["joint_shock", "mean_signed_error_pp"] == 2
    assert focal.at["equity_down", "mean_signed_error_pp"] == -3
    assert focal.at["rate_up", "predicted_gain_actual_loss_count"] == 1
    assert focal.at["neither", "under_fraction_all"] == 1
    assert focal.at["neither", "actual_loss_n"] == 0
    assert np.isnan(focal.at["neither", "actual_loss_mean_positive_underestimate_pp"])
    assert np.isnan(focal.at["neither", "actual_loss_mean_signed_error_pp"])
    assert focal.at["neither", "actual_gain_mean_signed_error_pp"] == 1
    assert focal.n.sum() == 4
    assert focal.total_absolute_error_pp.sum() == 8
    assert focal.error_share.sum() == pytest.approx(1)


def test_empty_buckets_remain_missing_instead_of_becoming_zero_error(small_source):
    rows, _ = prepare_rows(small_source)
    rows = rows[rows.regime != "joint_shock"]
    empty = summarize(rows, "regime", REGIMES).query("regime == 'joint_shock'")
    assert empty.n.eq(0).all() and empty.small_sample.all()
    assert empty.mae_pp.isna().all() and empty.mean_signed_error_pp.isna().all()
    assert empty.total_absolute_error_pp.eq(0).all()


def test_invalid_keys_shock_conflicts_and_missing_models_fail(small_source):
    with pytest.raises(ValueError, match="duplicate"):
        prepare_rows(pd.concat([small_source, small_source.iloc[:1]]))
    bad = small_source.copy()
    bad.loc[0, "shock_rate"] = 99
    with pytest.raises(ValueError, match="shocks differ"):
        prepare_rows(bad)
    with pytest.raises(ValueError, match="model missing"):
        prepare_rows(small_source[small_source.model != "spy_proxy"])
    bad = small_source.copy()
    bad.loc[0, "actual_loss_pct"] = 99
    with pytest.raises(ValueError, match="actual loss differs"):
        prepare_rows(bad)


def test_every_saved_regime_metric_matches_independent_source_slicing():
    root = Path(__file__).resolve().parents[1]
    out = root / "reports/portfolio/regime_stress"
    raw = pd.read_csv(root / "reports/portfolio/joint_stress/rolling.csv")
    raw = raw[raw.model.isin(MODELS)].copy()
    labels = []
    for row in raw.itertuples():
        if row.shock_market <= -0.05:
            labels.append("joint_shock" if row.shock_rate >= 20 else "equity_down")
        else:
            labels.append("rate_up" if row.shock_rate >= 20 else "neither")
    raw["regime"] = labels
    summary = pd.read_csv(out / "stress_validation_regime_summary.csv")
    assert len(summary) == 30 * 4 * 4
    for record in summary.itertuples():
        source = raw[(raw.subject == record.subject) & (raw.model == record.model)]
        group = source[source.regime == record.regime]
        error = group.actual_loss_pct - group.predicted_loss_pct
        assert record.n == len(group)
        assert record.actual_loss_n == (group.actual_loss_pct > 1e-9).sum()
        assert record.under_count == (error > 1e-9).sum()
        assert record.over_count == (error < -1e-9).sum()
        assert record.small_sample == (len(group) < 5)
        assert record.total_absolute_error_pp == pytest.approx(error.abs().sum(), abs=1e-7)
        if len(group):
            assert record.mae_pp == pytest.approx(error.abs().mean(), abs=1e-7)
            assert record.mean_signed_error_pp == pytest.approx(error.mean(), abs=1e-7)
            assert record.rmse_pp == pytest.approx(np.sqrt((error**2).mean()), abs=1e-7)
            assert record.mean_positive_underestimate_pp == pytest.approx(error.clip(lower=0).mean(), abs=1e-7)
            for mask, field in ((group.actual_loss_pct > 1e-9, "actual_loss_mean_signed_error_pp"),
                                (group.actual_loss_pct < -1e-9, "actual_gain_mean_signed_error_pp")):
                if mask.any():
                    assert getattr(record, field) == pytest.approx(error[mask].mean(), abs=1e-7)
                else:
                    assert np.isnan(getattr(record, field))
        else:
            assert np.isnan(record.mae_pp)
    for (subject, model), group in summary.groupby(["subject", "model"]):
        all_rows = raw[(raw.subject == subject) & (raw.model == model)]
        assert group.n.sum() == len(all_rows) == 145
        assert group.total_absolute_error_pp.sum() == pytest.approx((all_rows.actual_loss_pct - all_rows.predicted_loss_pct).abs().sum(), abs=1e-7)


def test_interval_membership_cross_bins_and_periods_match_source_dates():
    root = Path(__file__).resolve().parents[1]
    out = root / "reports/portfolio/regime_stress"
    intervals = pd.read_csv(out / "stress_validation_intervals.csv")
    prices = pd.read_csv(root / "data/portfolio/prices.csv", index_col="Date", parse_dates=True)
    factors = pd.read_csv(root / "data/portfolio/factors.csv", index_col="Date", parse_dates=True)
    assert len(intervals) == 145
    assert intervals.period.value_counts().to_dict() == {"late": 73, "early": 72}
    for row in intervals.itertuples():
        assert prices.index.get_loc(row.end) - prices.index.get_loc(row.start) == 10
        market = prices.loc[row.end, "SPY"] / prices.loc[row.start, "SPY"] - 1
        rate = 100 * (factors.DGS10.ffill().loc[row.end] - factors.DGS10.ffill().loc[row.start])
        assert row.shock_market == pytest.approx(market, abs=1e-11)
        assert row.shock_rate == pytest.approx(rate, abs=1e-9)
        market_bin = "selloff" if row.shock_market <= -.05 else "down" if row.shock_market <= -.02 else "flat" if row.shock_market < .02 else "up" if row.shock_market < .05 else "rally"
        rate_bin = "rate_down" if row.shock_rate <= -20 else "rate_middle" if row.shock_rate < 20 else "rate_up"
        assert row.cross_regime == f"{market_bin}__{rate_bin}"
    cross = pd.read_csv(out / "stress_validation_cross_summary.csv")
    assert len(cross) == 30 * 4 * 15
    assert cross.groupby(["subject", "model"]).n.sum().eq(145).all()
    periods = pd.read_csv(out / "stress_validation_period_summary.csv")
    assert len(periods) == 30 * 4 * 4 * 2
    for period, n in (("early", 72), ("late", 73)):
        assert periods[periods.period == period].groupby(["subject", "model"]).n.sum().eq(n).all()


def test_all_sensitivity_combinations_are_retained_with_no_best_cutoff_selection():
    out = Path(__file__).resolve().parents[1] / "reports/portfolio/regime_stress"
    sensitivity = pd.read_csv(out / "stress_validation_sensitivity.csv")
    assert len(sensitivity) == 9 * 2 * 4
    assert sensitivity.equity_cutoff.nunique() == sensitivity.rate_cutoff_bp.nunique() == 3
    assert sensitivity.groupby(["equity_cutoff", "rate_cutoff_bp", "subject"]).n.sum().eq(145).all()
    rows = pd.read_csv(out / "stress_validation_rows.csv")
    for record in sensitivity.itertuples():
        source = rows[(rows.subject == record.subject) & (rows.model == FOCAL)]
        down = source.shock_market <= record.equity_cutoff
        up = source.shock_rate >= record.rate_cutoff_bp
        mask = {"joint_shock": down & up, "equity_down": down & ~up,
                "rate_up": ~down & up, "neither": ~down & ~up}[record.regime]
        error = source.loc[mask, "actual_loss_pct"] - source.loc[mask, "predicted_loss_pct"]
        assert record.n == len(error)
        if len(error):
            assert record.mae_pp == pytest.approx(error.abs().mean(), abs=1e-7)


def test_cross_and_period_error_values_recompute_from_independent_groups():
    out = Path(__file__).resolve().parents[1] / "reports/portfolio/regime_stress"
    rows = pd.read_csv(out / "stress_validation_rows.csv")
    for dimension, filename, keys in (
        ("cross_regime", "cross_summary", ["subject", "model", "cross_regime"]),
        ("period", "period_summary", ["subject", "model", "period", "regime"]),
    ):
        summary = pd.read_csv(out / f"stress_validation_{filename}.csv")
        groups = {key: value for key, value in rows.groupby(keys)}
        for record in summary.itertuples():
            key = tuple(getattr(record, name) for name in keys)
            source = groups.get(key)
            if source is None:
                assert record.n == 0 and np.isnan(record.mae_pp)
            else:
                errors = source.actual_loss_pct - source.predicted_loss_pct
                assert record.n == len(errors)
                assert record.mae_pp == pytest.approx(errors.abs().mean(), abs=1e-7)
                assert record.mean_signed_error_pp == pytest.approx(errors.mean(), abs=1e-7)
                assert record.predicted_gain_actual_loss_count == ((source.actual_loss_pct > 1e-9) & (source.predicted_loss_pct < -1e-9)).sum()


def test_worst_windows_charts_and_preserved_upstream_hashes():
    root = Path(__file__).resolve().parents[1]
    out = root / "reports/portfolio/regime_stress"
    rows = pd.read_csv(out / "stress_validation_rows.csv")
    worst = pd.read_csv(out / "stress_validation_worst_windows.csv")
    assert len(rows) == 145 * 30 * 4
    assert len(worst) == 20
    for subject in ("before", "after"):
        expected = rows[(rows.subject == subject) & (rows.model == FOCAL)].nlargest(10, "absolute_error_pp")
        assert worst[worst.subject == subject].start.to_list() == expected.start.to_list()
    summary = pd.read_csv(out / "stress_validation_regime_summary.csv")
    for metric, name in (("mae_pp", "mae"), ("mean_signed_error_pp", "bias")):
        chart = json.loads((out / f"stress_validation_{name}_comparison.json").read_text())
        for point, regime in zip(chart["rows"], REGIMES):
            for subject, label in (("before", "변경 전"), ("after", "TLT 30%")):
                value = summary[(summary.subject == subject) & (summary.model == FOCAL) & (summary.regime == regime)].iloc[0]
                if value.n:
                    assert point[label] == pytest.approx(value[metric], abs=1e-9)
                else:
                    assert point[label] is None
    manifest = json.loads((out / "stress_validation_manifest.json").read_text())
    for key in ("sources_sha256", "upstream_inputs_sha256"):
        for name, digest in manifest[key].items():
            assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
    for folder, check in (("joint_stress", "checks.json"), ("direct_10d_stress", "stress_validation_checks.json")):
        base = root / "reports/portfolio" / folder
        previous = json.loads((base / check).read_text())
        for name, digest in previous["output_sha256"].items():
            assert hashlib.sha256((base / name).read_bytes()).hexdigest() == digest
