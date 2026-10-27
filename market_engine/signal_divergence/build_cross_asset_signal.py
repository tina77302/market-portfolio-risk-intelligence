from pathlib import Path
import pandas as pd
import numpy as np

INPUT = Path("data/processed/signal_divergence/cross_asset_dataset.csv")
OUTPUT = Path("data/processed/signal_divergence/cross_asset_signal.csv")

ASSETS = ["KOSPI200", "SPY", "TLT", "GLD"]
WINDOW = 20
MIN_HISTORY = 252

df = pd.read_csv(INPUT, parse_dates=["Date"]).sort_values("Date").reset_index(drop=True)

# Daily returns
for asset in ASSETS:
    df[f"{asset}_ret"] = df[asset].pct_change()

ret_cols = [f"{a}_ret" for a in ASSETS]

# 20D rolling pairwise correlations
pairs = []
for i in range(len(ret_cols)):
    for j in range(i + 1, len(ret_cols)):
        a, b = ret_cols[i], ret_cols[j]
        name = f"corr_{ASSETS[i]}_{ASSETS[j]}"
        df[name] = df[a].rolling(WINDOW).corr(df[b])
        pairs.append(name)

# Correlation-stress measures:
# 1) average absolute correlation = broad cross-asset coupling
# 2) maximum absolute correlation = strongest pairwise coupling
df["cross_asset_abs_corr_mean"] = df[pairs].abs().mean(axis=1)
df["cross_asset_abs_corr_max"] = df[pairs].abs().max(axis=1)

# Strictly past-only expanding percentiles
for col in ["cross_asset_abs_corr_mean", "cross_asset_abs_corr_max"]:
    x = df[col]
    pct = []

    for i in range(len(df)):
        hist = x.iloc[:i].dropna()

        if len(hist) < MIN_HISTORY or pd.isna(x.iloc[i]):
            pct.append(np.nan)
        else:
            pct.append((hist <= x.iloc[i]).mean())

    df[f"{col}_pct"] = pct

df["corr_extreme_90_count"] = (
    df[
        [
            "cross_asset_abs_corr_mean_pct",
            "cross_asset_abs_corr_max_pct",
        ]
    ] >= 0.90
).sum(axis=1)

df["corr_extreme_95_count"] = (
    df[
        [
            "cross_asset_abs_corr_mean_pct",
            "cross_asset_abs_corr_max_pct",
        ]
    ] >= 0.95
).sum(axis=1)

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
df.to_csv(OUTPUT, index=False)

print(f"Saved: {OUTPUT}")
print(f"Rows: {len(df):,}")
print("Period:", df.Date.min().date(), "->", df.Date.max().date())
print()
print(
    df[
        [
            "Date",
            "cross_asset_abs_corr_mean",
            "cross_asset_abs_corr_mean_pct",
            "cross_asset_abs_corr_max",
            "cross_asset_abs_corr_max_pct",
            "corr_extreme_90_count",
            "corr_extreme_95_count",
        ]
    ].tail(15).to_string(index=False)
)
