import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from analysis.portfolio_error_band_validation import error_offsets, make_bands, summarize


@pytest.fixture
def source():
    days = pd.bdate_range("2020-01-01", periods=761)
    return pd.DataFrame([
        {"subject": "p", "kind": "portfolio", "model": "joint_market_rate",
         "start": str(days[i*10].date()), "end": str(days[i*10+10].date()),
         "predicted_loss_pct": -10.0, "actual_loss_pct": i + 1 - 10.0,
         "shock_market": 0.01, "shock_rate": 2.0}
        for i in range(76)
    ])


def test_explicit_order_statistics_have_known_small_sample_ranks():
    assert error_offsets(np.arange(1, 31), "signed_errors") == (1, 30, 1, 30)
    assert error_offsets(np.arange(1, 31), "symmetric_absolute_errors") == (-28, 28, 28, 28)
    assert error_offsets(np.arange(1, 61), "signed_errors") == (3, 58, 3, 58)
    assert error_offsets(np.zeros(30), "signed_errors") == (0, 0, 1, 30)
    with pytest.raises(ValueError, match="unknown"):
        error_offsets([1, 2], "bad")
    with pytest.raises(ValueError, match="finite"):
        error_offsets([1, np.nan], "signed_errors")
    with pytest.raises(ValueError, match="between"):
        error_offsets([1, 2], "signed_errors", 1.0)


def test_immediately_previous_unmatured_window_is_excluded_and_warmup_is_null(source):
    rows = make_bands(source, min_errors=3, max_errors=5)
    focal = rows[rows.method == "signed_errors"].reset_index(drop=True)
    assert not focal.loc[:3, "ready"].any()
    assert focal.loc[:3, "lower_loss_pct"].isna().all()
    assert focal.loc[:3, "covered"].isna().all()
    first = focal.iloc[4]
    assert first.calibration_n == 3
    assert first.calibration_last_end == source.iloc[2].end < first.start
    assert first.lower_loss_pct == -9
    assert first.upper_loss_pct == -7
    assert first.predicted_loss_pct == -10  # Range need not contain the unchanged point.
    assert focal.iloc[-1].calibration_n == 5
    assert focal.iloc[-1].calibration_first_start == source.iloc[-7].start


def test_current_future_and_unmatured_outcomes_cannot_change_current_bounds(source):
    original = make_bands(source, min_errors=3, max_errors=5)
    changed_source = source.copy()
    # At row 20, row 19 ends exactly on its start; row 20 and later are future.
    changed_source.loc[19:, "actual_loss_pct"] += 10000
    changed = make_bands(changed_source, min_errors=3, max_errors=5)
    for method in ("signed_errors", "symmetric_absolute_errors"):
        old = original[(original.start == source.iloc[20].start) & (original.method == method)].iloc[0]
        new = changed[(changed.start == source.iloc[20].start) & (changed.method == method)].iloc[0]
        assert old.lower_loss_pct == new.lower_loss_pct
        assert old.upper_loss_pct == new.upper_loss_pct
        assert old.actual_loss_pct != new.actual_loss_pct


def test_calibration_never_pools_subjects(source):
    other = source.copy()
    other["subject"] = "q"
    other["actual_loss_pct"] += 1000
    single = make_bands(source, min_errors=3, max_errors=5)
    pooled = make_bands(pd.concat([source, other]), min_errors=3, max_errors=5)
    pd.testing.assert_frame_equal(single.reset_index(drop=True), pooled[pooled.subject == "p"].reset_index(drop=True))


def test_band_metrics_exclude_warmup_and_penalize_width_and_breaches(source):
    rows = make_bands(source, min_errors=3, max_errors=5)
    selected = rows[(rows.method == "signed_errors") & rows.ready].iloc[:2].copy()
    selected.loc[selected.index[0], ["actual_loss_pct", "covered", "upper_breach", "lower_breach", "upper_excess_pp", "lower_excess_pp", "interval_score"]] = [-7, True, False, False, 0, 0, 2]
    selected.loc[selected.index[1], ["actual_loss_pct", "covered", "upper_breach", "lower_breach", "upper_excess_pp", "lower_excess_pp", "interval_score"]] = [1, False, True, False, 7, 0, 142]
    selected["width_pp"] = 2
    warmup = rows[(rows.method == "signed_errors") & ~rows.ready].iloc[:1]
    row = summarize(pd.concat([warmup, selected])).iloc[0]
    assert row.total_n == 3 and row.evaluated_n == 2 and row.warmup_n == 1
    assert row.empirical_coverage == 0.5
    assert row.mean_interval_score == 72
    assert row.mean_upper_excess_all_pp == 3.5


def test_invalid_duplicate_or_overlapping_sources_are_rejected(source):
    with pytest.raises(ValueError, match="duplicate"):
        make_bands(pd.concat([source, source.iloc[:1]]))
    with pytest.raises(ValueError, match="minimum"):
        make_bands(source, min_errors=6, max_errors=5)
    bad = source.copy()
    bad.loc[1, "start"] = source.iloc[0].start[:-2] + "02"
    with pytest.raises(ValueError, match="overlapping"):
        make_bands(bad)


def test_all_saved_bounds_memberships_and_scores_match_independent_source_calculation():
    root = Path(__file__).resolve().parents[1]
    out = root / "reports/portfolio/error_band_stress"
    source = pd.read_csv(root / "reports/portfolio/joint_stress/rolling.csv")
    source = source[source.model == "joint_market_rate"]
    rows = pd.read_csv(out / "stress_validation_rows.csv")
    assert len(rows) == 30 * 145 * 2
    for subject, saved in rows.groupby("subject"):
        history = source[source.subject == subject].sort_values("start")
        for row in saved.itertuples():
            past = history.loc[history.end < row.start].sort_values("end").iloc[-60:]
            assert row.calibration_n == len(past)
            point = history.loc[history.start == row.start].iloc[0]
            assert row.predicted_loss_pct == point.predicted_loss_pct
            assert row.actual_loss_pct == point.actual_loss_pct
            if len(past) < 30:
                assert not row.ready and np.isnan(row.lower_loss_pct) and pd.isna(row.covered)
                continue
            assert row.ready and row.calibration_last_end < row.start
            errors = (past.actual_loss_pct - past.predicted_loss_pct).to_list()
            if row.method == "signed_errors":
                ordered = sorted(errors)
                low_rank = max(1, int(math.floor((len(errors)+1) / 20 + 1e-12)))
                high_rank = min(len(errors), int(math.ceil((len(errors)+1) * 19 / 20 - 1e-12)))
                low, high = ordered[low_rank-1], ordered[high_rank-1]
            else:
                ordered = sorted(abs(x) for x in errors)
                rank = min(len(errors), int(math.ceil((len(errors)+1) * 9 / 10 - 1e-12)))
                low, high = -ordered[rank-1], ordered[rank-1]
            lower, upper = row.predicted_loss_pct + low, row.predicted_loss_pct + high
            truth = row.actual_loss_pct
            assert row.lower_loss_pct == pytest.approx(lower, abs=1e-7)
            assert row.upper_loss_pct == pytest.approx(upper, abs=1e-7)
            assert bool(row.covered) == (lower <= truth <= upper)
            assert bool(row.upper_breach) == (truth > upper)
            assert bool(row.lower_breach) == (truth < lower)
            assert row.interval_score == pytest.approx(upper-lower + 20*(max(truth-upper, 0)+max(lower-truth, 0)), abs=1e-7)
            assert row.calibration_first_start == past.start.iloc[0]


def test_saved_summaries_use_correct_denominators_and_matched_samples():
    out = Path(__file__).resolve().parents[1] / "reports/portfolio/error_band_stress"
    rows = pd.read_csv(out / "stress_validation_rows.csv")
    for suffix, dimensions in (("summary", []), ("regime_summary", ["regime"]), ("period_summary", ["period"])):
        summary = pd.read_csv(out / f"stress_validation_{suffix}.csv")
        for record in summary.itertuples():
            group = rows[(rows.subject == record.subject) & (rows.method == record.method)]
            for field in dimensions:
                group = group[group[field] == getattr(record, field)]
            ready = group[group.ready]
            assert record.total_n == len(group)
            assert record.evaluated_n == len(ready)
            assert record.warmup_n == len(group) - len(ready)
            if len(ready):
                hit = (ready.actual_loss_pct >= ready.lower_loss_pct) & (ready.actual_loss_pct <= ready.upper_loss_pct)
                assert record.empirical_coverage == pytest.approx(hit.mean(), abs=1e-9)
                assert record.mean_width_pp == pytest.approx((ready.upper_loss_pct-ready.lower_loss_pct).mean(), abs=1e-7)
                assert record.upper_breach_n == (ready.actual_loss_pct > ready.upper_loss_pct).sum()
            else:
                assert np.isnan(record.empirical_coverage)
    for _, group in rows.groupby(["subject", "method"]):
        assert group.ready.sum() == 114 and (~group.ready).sum() == 31


def test_charts_warmup_gaps_and_upstream_artifacts_are_preserved():
    root = Path(__file__).resolve().parents[1]
    out = root / "reports/portfolio/error_band_stress"
    source = pd.read_csv(out / "stress_validation_rows.csv")
    for subject in ("before", "after"):
        chart = json.loads((out / f"stress_validation_{subject}_comparison.json").read_text())
        saved = source[(source.subject == subject) & (source.method == "signed_errors")].sort_values("start")
        assert len(chart["rows"]) == 145
        for point, row in zip(chart["rows"], saved.itertuples()):
            assert point["추정 손실"] == pytest.approx(row.predicted_loss_pct, abs=1e-9)
            if row.ready:
                assert point["하한"] == pytest.approx(row.lower_loss_pct, abs=1e-9)
                assert point["상한"] == pytest.approx(row.upper_loss_pct, abs=1e-9)
            else:
                assert point["하한"] is None and point["상한"] is None
    for folder, name in (("joint_stress", "checks.json"), ("direct_10d_stress", "stress_validation_checks.json"), ("regime_stress", "stress_validation_checks.json")):
        base = root / "reports/portfolio" / folder
        prior = json.loads((base / name).read_text())
        for filename, digest in prior["output_sha256"].items():
            assert hashlib.sha256((base / filename).read_bytes()).hexdigest() == digest
