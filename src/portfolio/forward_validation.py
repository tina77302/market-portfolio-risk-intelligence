"""Append-only paper-forward conditional loss validation.

python -m src.portfolio.forward_validation run --refresh
python -m src.portfolio.forward_validation status

Seals model/range rules, then freezes coefficients and calibration errors before
the first subsequent observed US session. Evaluation waits for ten more sessions.
"""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import tempfile
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from analysis.portfolio_error_band_validation import error_offsets
from analysis.portfolio_joint_stress_experiment import fit_ols
from analysis.portfolio_stress_validation import load_portfolios, subject_weights, validate_inputs

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STORE = ROOT / "data/portfolio_forward_validation"
SEED = ROOT / "reports/portfolio/joint_stress/rolling.csv"
NY = ZoneInfo("America/New_York")
RULES = {"model": "joint_market_rate", "window_returns": 756, "minimum_training_pairs": 252,
         "horizon_sessions": 10, "target_coverage": 0.9, "minimum_errors": 30, "maximum_errors": 60,
         "methods": ["signed_errors", "symmetric_absolute_errors"], "max_input_age_days": 4,
         "max_rate_carry_days": 4, "intercept_in_loss": False,
         "start_rule": "first observed SPY session strictly after NY issuance date",
         "evaluation_vintage": "both endpoints from same archived evaluation snapshot"}
COMPONENTS = ("src/portfolio/forward_validation.py", "analysis/portfolio_joint_stress_experiment.py",
              "analysis/portfolio_error_band_validation.py")


class IntegrityError(ValueError):
    pass


def utc_now():
    return datetime.now(timezone.utc)


def stamp(now):
    if now.tzinfo is None:
        raise ValueError("timezone-aware timestamp required")
    return now.astimezone(timezone.utc).isoformat()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_once(path, data):
    """Atomic create; never replace a sealed artifact, including on retries."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(tmp, path)
        except FileExistsError:
            if path.read_bytes() != data:
                raise IntegrityError(f"refusing to overwrite {path.name}")
    finally:
        os.unlink(tmp)


def seal(path, payload):
    envelope = {"payload": payload, "sha256": digest(canonical(payload))}
    write_once(path, canonical(envelope))
    return envelope


def read_seal(path):
    envelope = json.loads(Path(path).read_bytes())
    if digest(canonical(envelope["payload"])) != envelope["sha256"]:
        raise IntegrityError(f"hash mismatch: {Path(path).name}")
    return envelope


@contextmanager
def locked(store):
    Path(store).mkdir(parents=True, exist_ok=True)
    with (Path(store) / ".lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def initialize(store, now):
    path = Path(store) / "policy.json"
    components = {name: digest((ROOT / name).read_bytes()) for name in COMPONENTS}
    runtime = {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__}
    dependencies = "\n".join(sorted({f"{d.metadata['Name']}=={d.version}" for d in metadata.distributions()})) + "\n"
    if path.exists():
        policy = read_seal(path)
        if policy["payload"]["rules"] != RULES or policy["payload"]["code_sha256"] != components:
            raise IntegrityError("frozen rules/code changed; use a separately named study")
        if policy["payload"]["seed_sha256"] != digest(SEED.read_bytes()):
            raise IntegrityError("retrospective warm-start seed changed")
        if policy["payload"]["runtime"] != runtime:
            raise IntegrityError("frozen Python/numpy/pandas runtime changed")
        if now < datetime.fromisoformat(policy["payload"]["sealed_at"]):
            raise IntegrityError("runtime clock precedes policy seal")
        lockfile = Path(store) / "requirements.freeze.txt"
        if not lockfile.exists() or digest(lockfile.read_bytes()) != policy["payload"]["dependencies_sha256"]:
            raise IntegrityError("dependency lock missing or modified")
        return policy
    seeds = pd.read_csv(SEED)
    seed = seeds[seeds.model == RULES["model"]][["subject", "start", "end", "predicted_loss_pct", "actual_loss_pct"]]
    seed = seed.assign(origin="retrospective_seed")
    if (seed.end >= now.astimezone(NY).date().isoformat()).any():
        raise ValueError("seed outcomes are not completed before policy issuance")
    portfolios = load_portfolios()
    tickers = pd.read_csv(ROOT / "data/portfolio/prices.csv", nrows=0).columns[1:].tolist()
    payload = {"schema": 1, "sealed_at": stamp(now), "rules": RULES, "code_sha256": components,
               "seed_sha256": digest(SEED.read_bytes()), "seed_origin": "retrospective, already inspected; warm-start only",
               "seed_rows": seed.to_dict("records"), "tickers": tickers, "portfolios": portfolios,
               "runtime": runtime, "dependencies_sha256": digest(dependencies.encode()),
               "clock_assumption": "trusted runtime clock; local hashes are not external timestamp notarization"}
    write_once(Path(store) / "requirements.freeze.txt", dependencies.encode())
    return seal(path, payload)


def archive_inputs(store, prices, factors, now, provenance):
    today = pd.Timestamp(now.astimezone(NY).date())
    # Never treat an intraday/current-date provider bar as a completed session.
    prices, factors = prices.loc[prices.index < today], factors.loc[factors.index < today]
    validate_inputs(prices, factors)
    if len(prices) < 757:
        raise ValueError("at least 757 completed historical price observations required")
    pbytes, fbytes = prices.to_csv().encode(), factors.to_csv().encode()
    identity = digest(pbytes + fbytes)
    base = Path(store) / "inputs" / identity
    receipt = base / "receipt.json"
    if receipt.exists():
        saved = read_seal(receipt)
        for name, expected in saved["payload"]["files_sha256"].items():
            if digest((base / name).read_bytes()) != expected:
                raise IntegrityError("archived input modified")
        return identity, prices, factors
    write_once(base / "prices.csv", pbytes)
    write_once(base / "factors.csv", fbytes)
    seal(receipt, {"archived_at": stamp(now), "as_of": str(prices.index[-1].date()),
                   "provenance": provenance, "files_sha256": {"prices.csv": digest(pbytes), "factors.csv": digest(fbytes)}})
    return identity, prices, factors


def rate_level(factors, date):
    values = factors.loc[:date, "DGS10"].dropna()
    if values.empty or (pd.Timestamp(date) - values.index[-1]).days > RULES["max_rate_carry_days"]:
        raise ValueError("endpoint rate unavailable or too old")
    return float(values.iloc[-1]), str(values.index[-1].date())


def completed_entries(store, policy_hash):
    results = []
    for path in sorted((Path(store) / "entries").glob("*/result.json")):
        result = read_seal(path)["payload"]
        issue = read_seal(path.parent / "issue.json")
        if result["policy_sha256"] != policy_hash or result["issue_sha256"] != issue["sha256"]:
            raise IntegrityError("result belongs to another policy or modified issue")
        if result["start"] <= issue["payload"]["issued_ny_date"] or result["end"] <= result["start"]:
            raise IntegrityError("result is not a subsequent forward interval")
        results.append(result)
    return results


def audit_store(store, policy):
    store = Path(store)
    for receipt in (store / "inputs").glob("*/receipt.json"):
        payload = read_seal(receipt)["payload"]
        for name, expected in payload["files_sha256"].items():
            if digest((receipt.parent / name).read_bytes()) != expected:
                raise IntegrityError("archived input modified")
    for issue_path in (store / "entries").glob("*/issue.json"):
        issue = read_seal(issue_path)
        if issue["payload"]["policy_sha256"] != policy["sha256"]:
            raise IntegrityError("issue policy mismatch")
        read_seal(store / "inputs" / issue["payload"]["input_id"] / "receipt.json")
        for name in ("anchor.json", "result.json"):
            path = issue_path.parent / name
            if path.exists():
                payload = read_seal(path)["payload"]
                if payload["issue_sha256"] != issue["sha256"]:
                    raise IntegrityError("anchor/result issue mismatch")
                read_seal(store / "inputs" / payload["input_id"] / "receipt.json")
    completed_entries(store, policy["sha256"])


def freeze_issue(store, policy, prices, factors, input_id, now):
    rules = policy["payload"]["rules"]
    today = now.astimezone(NY).date()
    as_of = prices.index[-1]
    if (pd.Timestamp(today) - as_of).days > rules["max_input_age_days"]:
        return None, "WAITING_FOR_FRESH_INPUT"
    rate_level(factors, as_of)
    tickers = policy["payload"]["tickers"]
    if list(prices.columns) != tickers:
        raise ValueError("asset universe/order differs from frozen policy")
    p, f = prices.iloc[-757:], factors.loc[prices.index[-757:]]
    y = p.pct_change(fill_method=None).iloc[1:]
    x = pd.DataFrame({"market": y.SPY, "rate": f.DGS10.diff().iloc[1:] * 100})
    valid = x.notna().all(axis=1)
    beta, intercept, n, condition = fit_ols(x.loc[valid], y.loc[valid])
    history = list(policy["payload"]["seed_rows"])
    for result in completed_entries(store, policy["sha256"]):
        if result["evaluated_at"] > stamp(now):
            raise IntegrityError("result timestamp is in the future")
        for row in result["rows"]:
            history.append({"subject": row["subject"], "start": result["start"], "end": result["end"],
                            "actual_loss_pct": row["actual_loss_pct"], "predicted_loss_pct": row["predicted_loss_pct"],
                            "origin": "forward:" + result["issue_sha256"]})
    history = pd.DataFrame(history)
    subjects = subject_weights(prices, policy["payload"]["portfolios"])
    calibrations = {}
    for subject in subjects:
        eligible = history[(history.subject == subject) & (history.end <= str(as_of.date()))].sort_values("end").tail(rules["maximum_errors"])
        if eligible.duplicated(["start", "end"]).any():
            raise IntegrityError("duplicated calibration outcomes")
        errors = eligible.actual_loss_pct.to_numpy() - eligible.predicted_loss_pct.to_numpy()
        bounds = {}
        if len(errors) >= rules["minimum_errors"]:
            for method in rules["methods"]:
                low, high, lr, ur = error_offsets(errors, method, rules["target_coverage"])
                bounds[method] = {"lower_offset_pp": low, "upper_offset_pp": high, "lower_rank": lr, "upper_rank": ur}
        calibrations[subject] = {"n": len(errors), "ready": bool(bounds), "bounds": bounds,
                                 "past_rows": eligible.to_dict("records")}
    payload = {"issued_at": stamp(now), "issued_ny_date": str(today), "policy_sha256": policy["sha256"],
               "input_id": input_id, "training_as_of": str(as_of.date()), "training_pairs": n,
               "condition": condition, "beta": {t: {"market": float(beta[0, i]), "rate": float(beta[1, i])} for i, t in enumerate(tickers)},
               "fitted_intercept_excluded": {t: float(intercept[i]) for i, t in enumerate(tickers)},
               "subjects": subjects, "calibrations": calibrations, "prospective": True,
               "prediction_type": "conditional on subsequently observed factor shocks; not an issued future loss forecast"}
    identity = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    seal(Path(store) / "entries" / identity / "issue.json", payload)
    return identity, "WAITING_FOR_START_SESSION"


def advance_entry(folder, policy, prices, factors, input_id, now):
    issue = read_seal(folder / "issue.json")
    if now < datetime.fromisoformat(issue["payload"]["issued_at"]):
        raise IntegrityError("runtime clock precedes issue timestamp")
    if issue["payload"]["policy_sha256"] != policy["sha256"]:
        raise IntegrityError("issue policy mismatch")
    if (folder / "result.json").exists():
        read_seal(folder / "result.json")
        return "EVALUATED"
    future = prices.index[prices.index > pd.Timestamp(issue["payload"]["issued_ny_date"])]
    if not len(future):
        return "WAITING_FOR_START_SESSION"
    start = future[0]
    anchor_path = folder / "anchor.json"
    if not anchor_path.exists():
        seal(anchor_path, {"start": str(start.date()), "observed_at": stamp(now), "input_id": input_id,
                           "issue_sha256": issue["sha256"], "adjusted_start_prices": {t: float(prices.at[start, t]) for t in prices.columns}})
    anchor = read_seal(anchor_path)
    if anchor["payload"]["start"] != str(start.date()) or anchor["payload"]["issue_sha256"] != issue["sha256"]:
        raise IntegrityError("start session changed after anchoring")
    if len(future) < RULES["horizon_sessions"] + 1:
        return "WAITING_FOR_OUTCOME"
    end = future[RULES["horizon_sessions"]]
    try:
        r0, d0 = rate_level(factors, start)
        r1, d1 = rate_level(factors, end)
    except ValueError:
        return "WAITING_FOR_ENDPOINT_RATE"
    market = float(prices.at[end, "SPY"] / prices.at[start, "SPY"] - 1)
    rate = (r1 - r0) * 100
    returns = prices.loc[end] / prices.loc[start] - 1
    rows = []
    for subject, weights in issue["payload"]["subjects"].items():
        coefficients = issue["payload"]["beta"]
        point = -100 * sum(w * (coefficients[t]["market"] * market + coefficients[t]["rate"] * rate) for t, w in weights.items())
        actual = -100 * sum(w * float(returns[t]) for t, w in weights.items())
        bands = {}
        for method, offsets in issue["payload"]["calibrations"][subject]["bounds"].items():
            low, high = point + offsets["lower_offset_pp"], point + offsets["upper_offset_pp"]
            above, below = max(actual - high, 0), max(low - actual, 0)
            bands[method] = {"lower_loss_pct": low, "upper_loss_pct": high, "covered": low <= actual <= high,
                             "width_pp": high - low, "upper_excess_pp": above,
                             "interval_score": high - low + 20 * (above + below)}
        rows.append({"subject": subject, "predicted_loss_pct": point, "actual_loss_pct": actual,
                     "error_pp": actual - point, "bands": bands})
    seal(folder / "result.json", {"evaluated_at": stamp(now), "policy_sha256": policy["sha256"],
        "issue_sha256": issue["sha256"], "input_id": input_id, "start": str(start.date()), "end": str(end.date()),
        "rate_observation_dates": [d0, d1], "shock_market": market, "shock_rate_bp": rate, "rows": rows,
        "start_price_revision": {t: float(prices.at[start, t]) - anchor["payload"]["adjusted_start_prices"][t] for t in prices.columns},
        "vintage_policy": RULES["evaluation_vintage"]})
    return "EVALUATED"


def save_status(store, payload):
    # Status is a disposable projection; sealed policy/issues/results are immutable.
    path = Path(store) / "status.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    policy = read_seal(Path(store) / "policy.json")
    records = []
    for result in completed_entries(store, policy["sha256"]):
        for row in result["rows"]:
            for method, band in row["bands"].items():
                records.append({"subject": row["subject"], "method": method, "start": result["start"], "end": result["end"],
                                "point_loss_pct": row["predicted_loss_pct"], "actual_loss_pct": row["actual_loss_pct"],
                                "absolute_error_pp": abs(row["error_pp"]), **band})
    columns = ["subject", "method", "n", "mae_pp", "coverage", "mean_width_pp", "upper_breach_n", "max_upper_excess_pp", "mean_interval_score"]
    summaries = []
    if records:
        data = pd.DataFrame(records)
        data.to_csv(Path(store) / "evaluations.csv", index=False)
        for (subject, method), group in data.groupby(["subject", "method"]):
            summaries.append({"subject": subject, "method": method, "n": len(group), "mae_pp": group.absolute_error_pp.mean(),
                              "coverage": group.covered.mean(), "mean_width_pp": group.width_pp.mean(),
                              "upper_breach_n": int((group.upper_excess_pp > 0).sum()),
                              "max_upper_excess_pp": group.upper_excess_pp.max(), "mean_interval_score": group.interval_score.mean()})
    pd.DataFrame(summaries, columns=columns).to_csv(Path(store) / "summary.csv", index=False)
    return payload


def cycle(store, prices=None, factors=None, now=None, fetch_error=None):
    now = now or utc_now()
    store = Path(store)
    with locked(store):
        policy = initialize(store, now)
        audit_store(store, policy)
        if fetch_error:
            return save_status(store, {"at": stamp(now), "status": "WAITING_FOR_INPUT", "fetch_error_type": fetch_error,
                                       "last_archived_input_as_of": max([read_seal(p)["payload"]["as_of"] for p in (store / "inputs").glob("*/receipt.json")], default=None),
                                       "prospective_evaluations": len(completed_entries(store, policy["sha256"]))})
        try:
            input_id, prices, factors = archive_inputs(store, prices, factors, now, "local validated CSV or Yahoo/FRED refresh")
        except IntegrityError:
            raise
        except ValueError as exc:
            return save_status(store, {"at": stamp(now), "status": "WAITING_FOR_INPUT", "reason": str(exc),
                                      "prospective_evaluations": len(completed_entries(store, policy["sha256"]))})
        if list(prices.columns) != policy["payload"]["tickers"]:
            return save_status(store, {"at": stamp(now), "status": "WAITING_FOR_INPUT", "reason": "asset universe/order differs from frozen policy",
                                      "prospective_evaluations": len(completed_entries(store, policy["sha256"]))})
        statuses = {}
        for folder in sorted((store / "entries").glob("*")):
            statuses[folder.name] = advance_entry(folder, policy, prices, factors, input_id, now)
        pending = [key for key, value in statuses.items() if value != "EVALUATED"]
        if pending:
            status = statuses[pending[-1]]
        else:
            try:
                identity, status = freeze_issue(store, policy, prices, factors, input_id, now)
            except IntegrityError:
                raise
            except ValueError as exc:
                return save_status(store, {"at": stamp(now), "status": "WAITING_FOR_INPUT", "reason": str(exc),
                                          "prospective_evaluations": len(completed_entries(store, policy["sha256"]))})
            if identity:
                statuses[identity] = status
        return save_status(store, {"at": stamp(now), "status": status, "policy_sha256": policy["sha256"],
            "input_as_of": str(prices.index[-1].date()), "entries": statuses,
            "prospective_evaluations": len(completed_entries(store, policy["sha256"])),
            "label": "paper-forward conditional validation; historical seed is not forward evidence"})


def refresh_inputs():
    from src.portfolio.data import fetch_dgs10, fetch_prices
    from src.portfolio.universe import load_universe
    rate = fetch_dgs10("2018-01-01")
    panel = fetch_prices(load_universe().index, "2018-01-01")
    days = panel.index[panel.SPY.notna()]
    prices = panel.loc[days].drop(columns="VIX")
    factors = pd.DataFrame({"VIX": panel.loc[days, "VIX"], "DGS10": rate.DGS10.reindex(days)})
    return prices, factors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["run", "status"])
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--prices", type=Path, default=ROOT / "data/portfolio/prices.csv")
    parser.add_argument("--factors", type=Path, default=ROOT / "data/portfolio/factors.csv")
    args = parser.parse_args()
    if args.command == "status":
        with locked(args.store):
            audit_store(args.store, read_seal(args.store / "policy.json"))
        print((args.store / "status.json").read_text())
        return
    if args.refresh:
        try:
            prices, factors = refresh_inputs()
        except Exception as exc:
            print(json.dumps(cycle(args.store, fetch_error=type(exc).__name__), ensure_ascii=False, indent=2))
            return
    else:
        prices = pd.read_csv(args.prices, index_col="Date", parse_dates=True)
        factors = pd.read_csv(args.factors, index_col="Date", parse_dates=True)
    print(json.dumps(cycle(args.store, prices, factors), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
