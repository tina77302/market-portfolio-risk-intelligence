from pathlib import Path
import pandas as pd
import numpy as np

INPUT = Path("data/processed/signal_divergence/fx_features.csv")
OUTPUT = Path("data/processed/signal_divergence/fx_signal.csv")

df = pd.read_csv(INPUT, parse_dates=["Date"]).sort_values("Date").reset_index(drop=True)

SIGNALS = [
    "FX_1D_Return",
    "FX_5D_Return",
    "FX_20D_Return",
    "FX_252D_ZScore",
]

MIN_HISTORY = 252

for col in SIGNALS:
    x = df[col]

    df[f"{col}_pct"] = [
        np.nan
        if i < MIN_HISTORY or pd.isna(x.iloc[i])
        else (x.iloc[:i].dropna() <= x.iloc[i]).mean()
        for i in range(len(df))
    ]

pct_cols = [f"{c}_pct" for c in SIGNALS]

df["fx_percentile_mean"] = df[pct_cols].mean(axis=1, skipna=False)
df["fx_extreme_90_count"] = (df[pct_cols] >= 0.90).sum(axis=1)
df["fx_extreme_95_count"] = (df[pct_cols] >= 0.95).sum(axis=1)

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
df.to_csv(OUTPUT, index=False)

print(f"Saved: {OUTPUT}")
print(f"Rows: {len(df):,}")

show = [
    "Date",
    "USDKRW",
    "FX_1D_Return_pct",
    "FX_5D_Return_pct",
    "FX_20D_Return_pct",
    "FX_252D_ZScore_pct",
    "fx_percentile_mean",
    "fx_extreme_90_count",
    "fx_extreme_95_count",
]

october = df[
    (df["Date"] >= "2026-10-01") &
    (df["Date"] <= "2026-10-16")
]

print(october[show].to_string(index=False))
