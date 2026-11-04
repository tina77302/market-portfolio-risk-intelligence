from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
from pathlib import Path
import urllib.request
import zipfile

import numpy as np
import pandas as pd
import pytest

from src.portfolio.forward_validation import (
    IntegrityError, NY, RULES, canonical, cycle, digest, read_seal, write_once,
)


@pytest.fixture
def market():
    root = Path(__file__).resolve().parents[1]
    tickers = pd.read_csv(root / "data/portfolio/prices.csv", nrows=0).columns[1:]
    rng = np.random.default_rng(321)
    days = pd.bdate_range("2025-01-01", periods=850)
    m = rng.normal(0, .008, len(days))
    r = rng.normal(0, 2, len(days))
    prices = pd.DataFrame(index=days)
    for i, ticker in enumerate(tickers):
        returns = m if ticker == "SPY" else (0.8 + i/50)*m - .0004*r + rng.normal(0, .001, len(days))
        prices[ticker] = 100 * np.cumprod(1 + returns)
    factors = pd.DataFrame({"DGS10": 3+np.cumsum(r)/100, "VIX": 25+np.cumsum(rng.normal(0, .05, len(days)))}, index=days)
    prices.index.name = factors.index.name = "Date"
    return prices, factors


def after(day):
    return datetime.combine(pd.Timestamp(day).date() + timedelta(days=1), datetime.min.time(), timezone.utc) + timedelta(hours=12)


def first_issue(store):
    return sorted((store / "entries").glob("*/issue.json"))[0]


def test_stale_input_and_collection_error_never_create_a_forward_score(tmp_path, market):
    p, f = market
    result = cycle(tmp_path, p.iloc[:800], f.iloc[:800], after(p.index[810]))
    assert result["status"] == "WAITING_FOR_FRESH_INPUT"
    assert result["prospective_evaluations"] == 0
    assert not list((tmp_path / "entries").glob("*"))
    result = cycle(tmp_path, now=after(p.index[811]), fetch_error="ConnectionError")
    assert result["status"] == "WAITING_FOR_INPUT"
    assert result["prospective_evaluations"] == 0


def test_prestart_coefficients_and_calibration_are_frozen(tmp_path, market):
    p, f = market
    now = after(p.index[799])
    result = cycle(tmp_path, p.iloc[:800], f.iloc[:800], now)
    assert result["status"] == "WAITING_FOR_START_SESSION"
    path = first_issue(tmp_path)
    issue = read_seal(path)["payload"]
    assert issue["training_as_of"] < issue["issued_ny_date"]
    assert issue["training_pairs"] == 756
    for calibration in issue["calibrations"].values():
        assert calibration["n"] == RULES["maximum_errors"]
        assert max(row["end"] for row in calibration["past_rows"]) <= issue["training_as_of"]
    np.testing.assert_allclose([issue["beta"]["SPY"]["market"], issue["beta"]["SPY"]["rate"]], [1, 0], atol=1e-10)
    assert not (path.parent / "result.json").exists()


def test_waiting_maturity_evaluation_and_reruns_are_idempotent(tmp_path, market):
    p, f = market
    cycle(tmp_path, p.iloc[:800], f.iloc[:800], after(p.index[799]))
    issue_path = first_issue(tmp_path)
    frozen = issue_path.read_bytes()
    issue = read_seal(issue_path)["payload"]
    future = p.index[p.index > pd.Timestamp(issue["issued_ny_date"])]
    early = p.index.get_loc(future[8])+1
    waiting = cycle(tmp_path, p.iloc[:early], f.iloc[:early], after(p.index[early-1]))
    assert waiting["status"] == "WAITING_FOR_OUTCOME"
    assert waiting["prospective_evaluations"] == 0
    stop = p.index.get_loc(future[10])+1
    evaluated = cycle(tmp_path, p.iloc[:stop], f.iloc[:stop], after(p.index[stop-1]))
    assert evaluated["prospective_evaluations"] == 1
    assert issue_path.read_bytes() == frozen
    result_path = issue_path.parent / "result.json"
    original_result = result_path.read_bytes()
    result = read_seal(result_path)["payload"]
    assert result["start"] > issue["issued_ny_date"]
    assert p.index.get_loc(result["end"]) - p.index.get_loc(result["start"]) == 10
    again = cycle(tmp_path, p.iloc[:stop], f.iloc[:stop], after(p.index[stop-1])+timedelta(minutes=1))
    assert again["prospective_evaluations"] == 1
    assert result_path.read_bytes() == original_result
    assert len(list((tmp_path / "entries").glob("*/issue.json"))) == 2
    summary = pd.read_csv(tmp_path / "summary.csv")
    assert len(summary) == 60 and summary.n.eq(1).all()


def test_evaluation_uses_frozen_betas_and_same_vintage_endpoints(tmp_path, market):
    p, f = market
    cycle(tmp_path, p.iloc[:800], f.iloc[:800], after(p.index[799]))
    path = first_issue(tmp_path)
    issue = read_seal(path)["payload"]
    future = p.index[p.index > pd.Timestamp(issue["issued_ny_date"])]
    anchor_stop = p.index.get_loc(future[0])+1
    cycle(tmp_path, p.iloc[:anchor_stop], f.iloc[:anchor_stop], after(future[0]))
    stop = p.index.get_loc(future[10])+1
    revised = p.copy()
    revised["AAPL"] *= 1.2
    cycle(tmp_path, revised.iloc[:stop], f.iloc[:stop], after(future[10]))
    result = read_seal(path.parent / "result.json")["payload"]
    assert result["start_price_revision"]["AAPL"] > 0
    for row in result["rows"]:
        weights = issue["subjects"][row["subject"]]
        truth = -100*sum(w*(p.at[future[10], t]/p.at[future[0], t]-1) for t,w in weights.items())
        expected = -100*sum(w*(issue["beta"][t]["market"]*result["shock_market"] + issue["beta"][t]["rate"]*result["shock_rate_bp"]) for t,w in weights.items())
        assert row["actual_loss_pct"] == pytest.approx(truth)
        assert row["predicted_loss_pct"] == pytest.approx(expected)


def test_hash_tampering_and_overwrites_fail_closed(tmp_path, market):
    write_once(tmp_path / "example", b"original")
    write_once(tmp_path / "example", b"original")
    with pytest.raises(IntegrityError):
        write_once(tmp_path / "example", b"changed")
    p, f = market
    cycle(tmp_path, p.iloc[:800], f.iloc[:800], after(p.index[799]))
    path = first_issue(tmp_path)
    issue = json.loads(path.read_bytes())
    issue["payload"]["training_pairs"] = 1
    path.write_text(json.dumps(issue))
    with pytest.raises(IntegrityError, match="hash mismatch"):
        cycle(tmp_path, p.iloc[:810], f.iloc[:810], after(p.index[809]))


def test_policy_rule_change_and_input_archive_tampering_are_detected(tmp_path, market):
    p, f = market
    now = after(p.index[799])
    cycle(tmp_path, p.iloc[:800], f.iloc[:800], now)
    receipt = next((tmp_path / "inputs").glob("*/prices.csv"))
    receipt.write_text("modified")
    with pytest.raises(IntegrityError, match="archived input"):
        cycle(tmp_path, p.iloc[:800], f.iloc[:800], now)
    policy_path = tmp_path / "policy.json"
    envelope = read_seal(policy_path)
    envelope["payload"]["rules"]["window_returns"] = 10
    envelope["sha256"] = digest(canonical(envelope["payload"]))
    policy_path.write_text(json.dumps(envelope))
    with pytest.raises(IntegrityError, match="rules/code"):
        cycle(tmp_path, p.iloc[:800], f.iloc[:800], now)


def test_current_date_bars_are_never_assumed_complete(tmp_path, market):
    p, f = market
    today = p.index[799]
    now = datetime.combine(today.date(), datetime.min.time(), timezone.utc) + timedelta(hours=16)
    cycle(tmp_path, p.iloc[:800], f.iloc[:800], now)
    issue = read_seal(first_issue(tmp_path))["payload"]
    assert issue["training_as_of"] == str(p.index[798].date())
    assert issue["training_as_of"] < str(now.astimezone(NY).date())


def test_endpoint_rate_waits_without_saving_a_synthetic_outcome(tmp_path, market):
    p, f = market
    cycle(tmp_path, p.iloc[:800], f.iloc[:800], after(p.index[799]))
    path = first_issue(tmp_path)
    issue = read_seal(path)["payload"]
    future = p.index[p.index > pd.Timestamp(issue["issued_ny_date"])]
    end = future[10]
    stop = p.index.get_loc(end)+1
    missing = f.copy()
    missing.loc[(missing.index <= end) & (missing.index >= end-pd.Timedelta(days=8)), "DGS10"] = np.nan
    waiting = cycle(tmp_path, p.iloc[:stop], missing.iloc[:stop], after(end))
    assert waiting["status"] == "WAITING_FOR_ENDPOINT_RATE"
    assert not (path.parent / "result.json").exists()
    done = cycle(tmp_path, p.iloc[:stop], f.iloc[:stop], after(end)+timedelta(minutes=1))
    assert done["prospective_evaluations"] == 1
    new_issue_path = sorted((tmp_path / "entries").glob("*/issue.json"))[-1]
    new_issue = read_seal(new_issue_path)["payload"]
    assert any(row["origin"].startswith("forward:") for row in new_issue["calibrations"]["before"]["past_rows"])


def test_clock_rollback_and_missing_dependency_lock_fail_closed(tmp_path, market):
    p, f = market
    now = after(p.index[799])
    cycle(tmp_path, p.iloc[:800], f.iloc[:800], now)
    with pytest.raises(IntegrityError, match="clock"):
        cycle(tmp_path, p.iloc[:800], f.iloc[:800], now-timedelta(days=1))
    (tmp_path / "requirements.freeze.txt").unlink()
    with pytest.raises(IntegrityError, match="dependency lock"):
        cycle(tmp_path, p.iloc[:800], f.iloc[:800], now)


def test_artifact_restore_rejects_unsafe_paths_and_strips_redirect_credentials(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts/restore_portfolio_forward_state.py"
    spec = importlib.util.spec_from_file_location("forward_restore", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    bad = io.BytesIO()
    with zipfile.ZipFile(bad, "w") as zipped:
        zipped.writestr("../escape", "bad")
    with pytest.raises(ValueError, match="unsafe"):
        module.extract_state(bad.getvalue(), tmp_path)
    good = io.BytesIO()
    with zipfile.ZipFile(good, "w") as zipped:
        zipped.writestr("policy.json", "{}")
    module.extract_state(good.getvalue(), tmp_path)
    req = urllib.request.Request("https://api.github.com/artifact", headers={"Authorization": "Bearer test-token"})
    redirected = module.SafeRedirect().redirect_request(req, None, 302, "Found", {}, "https://blob.example/zip")
    assert redirected.get_header("Authorization") is None
