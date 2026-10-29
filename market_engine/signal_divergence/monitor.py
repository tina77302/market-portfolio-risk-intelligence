"""Read-only integration of frozen Korea research; never trains or fills observations."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SIGNALS = ["decline_1d_breadth", "loss_2pct_1d_breadth", "loss_5pct_5d_breadth",
           "drawdown_10pct_breadth", "high_vol_breadth", "abnormal_volume_breadth"]
PCTS = [f"{s}_pct" for s in SIGNALS]
CORR = ["cross_asset_abs_corr_mean_pct", "cross_asset_abs_corr_max_pct"]
SOURCES = {
    "v1": "data/processed/early_warning_v2/korea_oos_predictions_v1_reproduction_10d.csv",
    "msi": "data/processed/early_warning_v2/korea_feature_matrix_v1_reproduction.csv",
    "breadth": "data/processed/signal_divergence/korea_breadth_features.csv",
    "correlation": "data/processed/signal_divergence/cross_asset_signal.csv",
}
COLUMNS = {"v1": ["Prob_XGBoost"], "msi": ["Korea_MSI", "Stress_Threshold"],
           "breadth": SIGNALS + PCTS, "correlation": CORR}


def checked(frame: pd.DataFrame, columns: list[str], name: str) -> pd.DataFrame:
    """Reject ambiguous units and dates rather than silently repairing research."""
    frame = frame.copy()
    if not {"Date", *columns}.issubset(frame.columns):
        raise ValueError(f"{name}: missing required columns")
    frame["Date"] = pd.to_datetime(frame["Date"], errors="raise")
    if frame.Date.isna().any() or frame.Date.duplicated().any():
        raise ValueError(f"{name}: missing or duplicate dates")
    if (frame.Date != frame.Date.dt.normalize()).any():
        raise ValueError(f"{name}: expected daily trading dates")
    for c in columns:
        frame[c] = pd.to_numeric(frame[c], errors="raise")
        if np.isinf(frame[c]).any():
            raise ValueError(f"{name}: infinite {c}")
        if c in SIGNALS + PCTS + CORR + ["Prob_XGBoost"]:
            if not frame[c].dropna().between(0, 1).all():
                raise ValueError(f"{name}: {c} must use 0–1 units, not percent units")
    return frame.sort_values("Date").reset_index(drop=True)


def past_percentile(series: pd.Series, minimum: int = 252) -> pd.Series:
    """Frozen research empirical CDF: current value ranked against strictly prior rows."""
    return pd.Series([
        np.nan if i < minimum or pd.isna(x) else (series.iloc[:i].dropna() <= x).mean()
        for i, x in enumerate(series)
    ], index=series.index)


def classify(risk: float, msi: float, threshold: float, persistent: float) -> tuple[str, str]:
    if any(pd.isna(x) for x in [risk, msi, threshold, persistent]):
        return "UNKNOWN / INSUFFICIENT DATA", "Required V1, MSI, official threshold or 3-observation breadth window unavailable."
    high, stress, breadth = risk >= .50, msi >= threshold, bool(persistent)
    if high:
        if stress or breadth:
            return "ALIGNED RISK", "V1 predicts elevated risk; current MSI stress or persistent breadth confirms deterioration."
        return "MODEL-LED WARNING", "V1 predicts elevated risk without MSI stress or persistent breadth confirmation."
    if stress:
        return "OBSERVED MSI STRESS", "Current stress is already visible to MSI; this is not a V1+MSI blind spot."
    if breadth:
        return "SIGNAL DIVERGENCE", "Persistent broad deterioration disagrees with low V1 risk while MSI remains below its official threshold."
    return "NORMAL", "V1 and MSI are below thresholds and no persistent breadth deterioration is confirmed."


def integrate(v1: pd.DataFrame, msi: pd.DataFrame, breadth: pd.DataFrame,
              correlation: pd.DataFrame) -> pd.DataFrame:
    frames = {k: checked(f, COLUMNS[k], k) for k, f in
              zip(SOURCES, [v1, msi, breadth, correlation])}
    # Union of actual primary-source dates: a missing breadth row must not compress the window.
    dates = sorted(set().union(*(set(frames[k].Date) for k in ["v1", "msi", "breadth"])))
    out = pd.DataFrame({"Date": pd.to_datetime(dates)})
    for k, frame in frames.items():
        out = out.merge(frame[["Date"] + COLUMNS[k]], on="Date", how="left", validate="one_to_one")
    complete = out[PCTS + SIGNALS].notna().all(axis=1)
    out["extreme_count"] = out[PCTS].ge(.90).sum(axis=1).where(complete)
    out["breadth_mean"] = out[PCTS].mean(axis=1, skipna=False)
    out["raw_breadth"] = out.extreme_count.ge(2).astype(float).where(complete)
    out["window_hits"] = out.raw_breadth.rolling(3, min_periods=3).sum()
    out["persistent"] = out.window_hits.ge(2).astype(float).where(out.window_hits.notna())
    out["correlation_count"] = out[CORR].ge(.90).sum(axis=1).where(out[CORR].notna().all(axis=1))
    assigned = [classify(*r) for r in out[["Prob_XGBoost", "Korea_MSI", "Stress_Threshold", "persistent"]].itertuples(index=False, name=None)]
    out["state"] = [s for s, _ in assigned]
    out["reason"] = [r for _, r in assigned]
    out["mode"] = np.where(out.Prob_XGBoost.notna(), "HISTORICAL OOS", "RESEARCH / EXPERIMENTAL")
    return out


def records(frame: pd.DataFrame) -> list[dict]:
    clean = frame.copy()
    clean["Date"] = clean.Date.dt.strftime("%Y-%m-%d")
    return json.loads(clean.to_json(orient="records", double_precision=10))


def export(root: Path = ROOT, output: Path | None = None) -> dict:
    frames, metadata, issues = {}, {}, []
    for k, relative in SOURCES.items():
        path = root / relative
        try:
            frame = checked(pd.read_csv(path), COLUMNS[k], k)
            metadata[k] = {"path": relative, "latest": None if frame.empty else str(frame.Date.max().date()),
                           "rows": len(frame), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        except (FileNotFoundError, ValueError, pd.errors.ParserError) as e:
            frame = pd.DataFrame(columns=["Date"] + COLUMNS[k])
            metadata[k] = {"path": relative, "latest": None, "rows": 0}
            issues.append(f"{k}: {e}")
        frames[k] = frame
    history = integrate(**{k: frames[k] for k in ["v1", "msi", "breadth", "correlation"]})
    # OOS is the monitoring start; earlier inputs remain available to persistence calculations.
    history = history[history.Date >= pd.Timestamp("2016-09-13")]
    rows = records(history)
    valid = [r for r in rows if r["state"] != "UNKNOWN / INSUFFICIENT DATA"]
    holdout = [r for r in rows if "2026-10-07" <= r["Date"] <= "2026-10-15"]
    # Read reported (rounded) holdout V1 values from the frozen experiment document.
    experiment = root / "market_engine/early_warning_v2/EXPERIMENTS.md"
    reported = {}
    if experiment.exists():
        for line in experiment.read_text().splitlines():
            cells = [x.strip() for x in line.split("|")]
            if len(cells) == 6 and cells[1].startswith("2026-10-"):
                reported[cells[1]] = {"reported_v1_percent": float(cells[3].rstrip("%")),
                                       "reported_return_percent": float(cells[2].rstrip("%"))}
    for row in holdout:
        row.update(reported.get(row["Date"], {}))
    payload = {"schema_version": 1, "dataset": "Frozen local historical research export; not live",
               "sources": metadata, "issues": issues, "latest": rows[-1] if rows else None,
               "last_complete": valid[-1] if valid else None, "history": rows, "holdout": holdout,
               "evidence": {"eligible": 18, "detected": 6, "coverage": 33.3, "median_lead": 6,
                            "false_warnings_year": 4.2, "source": "market_engine/signal_divergence/VALIDATION.md",
                            "status": "Reported historical research results; not re-estimated or live accuracy"}}
    output = output or root / "frontend/public/data/korea-monitor.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n")
    csv = root / "data/processed/signal_divergence/monitor/korea_monitor_history.csv"
    csv.parent.mkdir(parents=True, exist_ok=True)
    history.to_csv(csv, index=False)
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = export(args.root, args.output)
    print(json.dumps({k: result[k] for k in ["dataset", "sources", "issues", "latest", "last_complete"]}, indent=2))
