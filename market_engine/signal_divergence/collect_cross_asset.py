from pathlib import Path
import pandas as pd
import yfinance as yf

START = "2006-01-01"
END = "2026-10-28"

TICKERS = {
    "KOSPI200": "^KS200",
    "SPY": "SPY",
    "TLT": "TLT",
    "GLD": "GLD",
}

OUTPUT = Path("data/raw/signal_divergence/cross_asset_prices.csv")

series = []

for name, ticker in TICKERS.items():
    print(f"Downloading {name} ({ticker})...")

    df = yf.download(
        ticker,
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
    )

    if df.empty:
        print(f"WARNING: no data for {name}")
        continue

    close = df["Close"]

    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]

    close = close.rename(name)
    series.append(close)

prices = pd.concat(series, axis=1).sort_index()
prices.index.name = "Date"

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
prices.to_csv(OUTPUT)

print()
print(f"Saved: {OUTPUT}")
print(f"Rows: {len(prices):,}")
print("Period:", prices.index.min().date(), "->", prices.index.max().date())
print()
print(prices.notna().sum())
print()
print(prices.tail())
