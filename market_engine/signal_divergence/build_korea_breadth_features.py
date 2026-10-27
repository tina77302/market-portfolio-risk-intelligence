from pathlib import Path
import pandas as pd
import numpy as np

INPUT = Path("data/raw/signal_divergence/korea_breadth/market_breadth.csv")
OUTPUT = Path("data/processed/signal_divergence/korea_breadth_features.csv")

df = pd.read_csv(INPUT, parse_dates=["Date"]).sort_values("Date").reset_index(drop=True)

SIGNALS = [
    "decline_1d_breadth",
    "loss_2pct_1d_breadth",
    "loss_5pct_5d_breadth",
    "drawdown_10pct_breadth",
    "high_vol_breadth",
    "abnormal_volume_breadth",
]

MIN_HISTORY = 252

for col in SIGNALS:
    x = df[col]

    # Strictly past-only expanding percentile:
    # today's observation is compared only with observations available before today.
    df[f"{col}_pct"] = [
        np.nan if i < MIN_HISTORY or pd.isna(x.iloc[i])
        else (x.iloc[:i].dropna() <= x.iloc[i]).mean()
        for i in range(len(df))
    ]

pct_cols = [f"{c}_pct" for c in SIGNALS]

# Descriptive breadth severity only.
# No operational threshold is selected here.
df["breadth_percentile_mean"] = df[pct_cols].mean(axis=1, skipna=False)
df["breadth_extreme_90_count"] = (df[pct_cols] >= 0.90).sum(axis=1)
df["breadth_extreme_95_count"] = (df[pct_cols] >= 0.95).sum(axis=1)

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
df.to_csv(OUTPUT, index=False)

october = df[
    (df["Date"] >= "2026-10-01") &
    (df["Date"] <= "2026-10-16")
]

show = [
    "Date",
    "decline_1d_breadth",
    "decline_1d_breadth_pct",
    "loss_2pct_1d_breadth",
    "loss_2pct_1d_breadth_pct",
    "loss_5pct_5d_breadth_pct",
    "drawdown_10pct_breadth_pct",
    "high_vol_breadth_pct",
    "abnormal_volume_breadth_pct",
    "breadth_percentile_mean",
    "breadth_extreme_90_count",
    "breadth_extreme_95_count",
]

print(f"Saved: {OUTPUT}")
print(october[show].to_string(index=False))
