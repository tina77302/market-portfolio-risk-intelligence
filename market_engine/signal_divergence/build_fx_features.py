from pathlib import Path
import pandas as pd

INPUT = Path("data/raw/signal_divergence/usdkrw.csv")
OUTPUT = Path("data/processed/signal_divergence/fx_features.csv")

df = pd.read_csv(INPUT, parse_dates=["Date"])
df = df[["Date", "Close_KRW=X"]].rename(columns={"Close_KRW=X": "USDKRW"})
df = df.sort_values("Date").drop_duplicates("Date").reset_index(drop=True)

df["FX_1D_Return"] = df["USDKRW"].pct_change(1)
df["FX_5D_Return"] = df["USDKRW"].pct_change(5)
df["FX_20D_Return"] = df["USDKRW"].pct_change(20)

past = df["USDKRW"].shift(1)
mean_252 = past.rolling(252, min_periods=126).mean()
std_252 = past.rolling(252, min_periods=126).std()

df["FX_252D_ZScore"] = (df["USDKRW"] - mean_252) / std_252

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
df.to_csv(OUTPUT, index=False)

print(f"Saved: {OUTPUT}")
print(f"Rows: {len(df):,}")
print(df.tail(10).to_string(index=False))
