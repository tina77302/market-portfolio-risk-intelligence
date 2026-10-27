from pathlib import Path
import yfinance as yf

START_DATE = "2006-01-01"
TICKER = "KRW=X"

OUTPUT = Path("data/raw/signal_divergence/usdkrw.csv")
OUTPUT.parent.mkdir(parents=True, exist_ok=True)

df = yf.download(
    TICKER,
    start=START_DATE,
    auto_adjust=False,
    progress=False,
)

if df.empty:
    raise RuntimeError("USD/KRW download returned no data.")

if hasattr(df.columns, "levels"):
    df.columns = [
        "_".join(str(x) for x in col if str(x))
        if isinstance(col, tuple)
        else str(col)
        for col in df.columns
    ]

df.index.name = "Date"
df.to_csv(OUTPUT)

print(f"Saved: {OUTPUT}")
print(f"Rows: {len(df):,}")
print(f"Period: {df.index.min().date()} -> {df.index.max().date()}")
print(df.tail())
