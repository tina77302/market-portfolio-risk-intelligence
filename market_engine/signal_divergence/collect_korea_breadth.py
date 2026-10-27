"""P2-A Korea listed-company breadth research.

CURRENT-UNIVERSE RETROSPECTIVE RESEARCH ONLY.

The universe is the current active KOSPI/KOSDAQ stock universe from the
project security master. Historical results therefore have survivorship bias
and must not be described as point-in-time constituent backtests.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf


ROOT = Path(__file__).resolve().parents[2]
MASTER = Path.home() / "market-stress-early-warning/data/paper/security-master.sqlite3"


def load_universe() -> pd.DataFrame:
    with sqlite3.connect(MASTER) as con:
        df = pd.read_sql_query(
            """
            SELECT
                market,
                exchange,
                symbol,
                ticker,
                provider_symbol,
                name,
                currency,
                security_type,
                active
            FROM securities
            WHERE market='korea'
              AND exchange IN ('KOSPI','KOSDAQ')
              AND security_type='Stock'
              AND active=1
            ORDER BY exchange, ticker
            """,
            con,
        )

    if len(df) != 2430:
        raise RuntimeError(f"Expected 2430 current active Korea stocks, got {len(df)}")

    if df["provider_symbol"].isna().any():
        raise RuntimeError("Missing provider_symbol")

    if df["provider_symbol"].duplicated().any():
        raise RuntimeError("Duplicate provider_symbol")

    return df


def download_chunk(symbols: list[str], start: str) -> pd.DataFrame:
    return yf.download(
        tickers=symbols,
        start=start,
        auto_adjust=False,
        actions=False,
        repair=False,
        group_by="column",
        threads=True,
        progress=False,
    )


def extract_field(raw: pd.DataFrame, field: str, symbols: list[str]) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame()

    if isinstance(raw.columns, pd.MultiIndex):
        level0 = raw.columns.get_level_values(0)

        if field not in level0:
            return pd.DataFrame(index=raw.index)

        x = raw[field].copy()

        if isinstance(x, pd.Series):
            x = x.to_frame()

        return x.reindex(columns=[s for s in symbols if s in x.columns])

    if len(symbols) == 1 and field in raw.columns:
        return raw[[field]].rename(columns={field: symbols[0]})

    return pd.DataFrame(index=raw.index)


def collect(
    universe: pd.DataFrame,
    start: str,
    chunk_size: int,
    cache: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    cache.mkdir(parents=True, exist_ok=True)

    close_parts = []
    volume_parts = []

    symbols = universe["provider_symbol"].tolist()

    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i:i + chunk_size]
        tag = f"{i:04d}_{i + len(chunk) - 1:04d}"

        close_path = cache / f"close_{tag}.pkl"
        volume_path = cache / f"volume_{tag}.pkl"

        if close_path.exists() and volume_path.exists():
            close = pd.read_pickle(close_path)
            volume = pd.read_pickle(volume_path)
            print(f"CACHE {tag}: {len(chunk)} symbols", flush=True)

        else:
            print(f"DOWNLOAD {tag}: {len(chunk)} symbols", flush=True)

            raw = download_chunk(chunk, start)

            close = extract_field(raw, "Adj Close", chunk)
            if close.empty:
                close = extract_field(raw, "Close", chunk)

            volume = extract_field(raw, "Volume", chunk)

            close.to_pickle(close_path)
            volume.to_pickle(volume_path)

            time.sleep(1)

        close_parts.append(close)
        volume_parts.append(volume)

    close = pd.concat(close_parts, axis=1)
    volume = pd.concat(volume_parts, axis=1)

    close = close.loc[:, ~close.columns.duplicated()]
    volume = volume.loc[:, ~volume.columns.duplicated()]

    return close.sort_index(), volume.sort_index()


def coverage(
    universe: pd.DataFrame,
    close: pd.DataFrame,
    volume: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for r in universe.itertuples():
        s = r.provider_symbol

        c = close[s] if s in close else pd.Series(dtype=float)
        v = volume[s] if s in volume else pd.Series(dtype=float)

        valid = c.dropna()

        rows.append(
            {
                "market": r.market,
                "exchange": r.exchange,
                "ticker": r.ticker,
                "provider_symbol": s,
                "name": r.name,
                "close_observations": int(c.notna().sum()),
                "volume_observations": int(v.notna().sum()),
                "first_close": valid.index.min() if len(valid) else pd.NaT,
                "last_close": valid.index.max() if len(valid) else pd.NaT,
                "has_252_close": bool(c.notna().sum() >= 252),
            }
        )

    return pd.DataFrame(rows)


def breadth_features(close: pd.DataFrame, volume: pd.DataFrame) -> pd.DataFrame:
    close = close.where(close > 0)

    r1 = close.pct_change(fill_method=None)
    r3 = close.pct_change(3, fill_method=None)
    r5 = close.pct_change(5, fill_method=None)

    rolling_high = close.rolling(60, min_periods=20).max()
    drawdown60 = close / rolling_high - 1

    vol20 = r1.rolling(20, min_periods=10).std()

    vol_base = volume.rolling(20, min_periods=10).median()
    abnormal_volume = volume / vol_base

    out = pd.DataFrame(index=close.index)

    # Cross-sectional deterioration / diffusion.
    out["coverage"] = close.notna().sum(axis=1)
    out["decline_1d_breadth"] = (r1 < 0).sum(axis=1) / r1.notna().sum(axis=1)
    out["loss_2pct_1d_breadth"] = (r1 <= -0.02).sum(axis=1) / r1.notna().sum(axis=1)
    out["loss_5pct_5d_breadth"] = (r5 <= -0.05).sum(axis=1) / r5.notna().sum(axis=1)
    out["drawdown_10pct_breadth"] = (
        (drawdown60 <= -0.10).sum(axis=1) / drawdown60.notna().sum(axis=1)
    )
    out["high_vol_breadth"] = (
        vol20.gt(vol20.rolling(252, min_periods=126).quantile(.90).shift(1)).sum(axis=1)
        / vol20.notna().sum(axis=1)
    )
    out["abnormal_volume_breadth"] = (
        (abnormal_volume >= 2).sum(axis=1) / abnormal_volume.notna().sum(axis=1)
    )

    # Equal-weight cross-sectional location/dispersion.
    out["ew_return_1d"] = r1.mean(axis=1)
    out["ew_return_3d"] = r3.mean(axis=1)
    out["ew_return_5d"] = r5.mean(axis=1)
    out["return_dispersion_1d"] = r1.std(axis=1)

    return out.replace([np.inf, -np.inf], np.nan)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--start", default="2015-01-01")
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--chunk-size", type=int, default=50)
    args = ap.parse_args()

    out = args.output
    out.mkdir(parents=True, exist_ok=True)

    universe = load_universe()

    if args.limit > 0:
        # Deterministic smoke sample spanning both exchanges.
        parts = []
        for exchange, group in universe.groupby("exchange"):
            n = min(
                len(group),
                round(args.limit * len(group) / 2430),
            )
            parts.append(group.sample(n=n, random_state=42))

        universe = pd.concat(parts, ignore_index=True)

    universe.to_csv(out / "UNIVERSE_MANIFEST.csv", index=False)

    close, volume = collect(
        universe,
        args.start,
        args.chunk_size,
        out / "raw_cache",
    )

    qa = coverage(universe, close, volume)
    qa.to_csv(out / "coverage_report.csv", index=False)

    breadth = breadth_features(close, volume)
    breadth.to_csv(out / "market_breadth.csv")

    summary = {
        "status": "CURRENT-UNIVERSE RETROSPECTIVE RESEARCH",
        "requested_universe": int(len(universe)),
        "symbols_with_any_close": int((qa.close_observations > 0).sum()),
        "symbols_with_252_close": int(qa.has_252_close.sum()),
        "latest_date": (
            str(pd.Timestamp(close.index.max()).date())
            if len(close.index)
            else None
        ),
        "survivorship_bias_warning": (
            "Current active KOSPI/KOSDAQ constituents are used retrospectively; "
            "historical membership is not reconstructed."
        ),
    }

    (out / "SMOKE_SUMMARY.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False)
    )

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print("P2-A collection complete:", out)


if __name__ == "__main__":
    main()
