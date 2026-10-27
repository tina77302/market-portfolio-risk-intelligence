from pathlib import Path
import pandas as pd

V1 = Path.home() / "market-stress-early-warning/data/processed/korea/korea_stress_index.csv"
RAW = Path("data/raw/signal_divergence/cross_asset_prices.csv")
OUT = Path("data/processed/signal_divergence/cross_asset_dataset.csv")

korea = pd.read_csv(V1, parse_dates=["Date"])[["Date", "KOSPI200"]].dropna()
global_px = pd.read_csv(RAW, parse_dates=["Date"])[["Date", "SPY", "TLT", "GLD"]]

df = korea.merge(global_px, on="Date", how="left").sort_values("Date")

# Fill short U.S.-market holiday gaps only.
for col in ["SPY", "TLT", "GLD"]:
    df[col] = df[col].ffill(limit=3)

df = df.dropna(subset=["SPY", "TLT", "GLD"]).reset_index(drop=True)

OUT.parent.mkdir(parents=True, exist_ok=True)
df.to_csv(OUT, index=False)

print(f"Saved: {OUT}")
print(f"Rows: {len(df):,}")
print("Period:", df.Date.min().date(), "->", df.Date.max().date())
print()
print("Missing values:")
print(df.isna().sum())
print()
print(df.tail(10).to_string(index=False))
