import argparse
import logging
from io import StringIO
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

from src.portfolio.universe import load_universe

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"
PRICES_PATH = RAW_DIR / "portfolio_prices.csv"
DGS10_PATH = RAW_DIR / "dgs10.csv"
QUALITY_PATH = RAW_DIR / "portfolio_data_quality.csv"

DEFAULT_START = "2018-01-01"
# 베타·상관·변동성 추정 기간: 최근 3년
WINDOW_DAYS = 756


def fetch_prices(tickers, start, end=None):
    """
    지원 자산과 VIX의 일별 종가를 Yahoo Finance에서 수집합니다.

    자산은 배당·분할을 반영한 수정종가(auto_adjust)를 사용합니다.
    VIX는 지수이므로 수정 여부와 관계없이 같은 값입니다.
    """
    symbols = list(tickers) + ["^VIX"]
    logger.info(f"Fetching {len(symbols)} symbols from {start}...")

    df = yf.download(
        symbols,
        start=start,
        end=end,
        auto_adjust=True,
        progress=False
    )

    df_close = df["Close"][symbols].copy()
    df_close = df_close.rename(columns={"^VIX": "VIX"})
    df_close.index = pd.to_datetime(df_close.index).tz_localize(None)
    df_close.index.name = "Date"

    logger.info(f"Prices fetched. Shape: {df_close.shape}")
    return df_close


def fetch_dgs10(start, end=None):
    """
    FRED에서 10년 국채금리(DGS10, %)를 수집합니다.

    채권시장 휴장일은 '.'로 들어오며 결측치로 그대로 둡니다.
    """
    url = (
        "https://fred.stlouisfed.org/graph/"
        f"fredgraph.csv?id=DGS10&cosd={start}"
    )
    if end:
        url += f"&coed={end}"

    resp = requests.get(url, timeout=60)
    resp.raise_for_status()

    df = pd.read_csv(
        StringIO(resp.text),
        parse_dates=["observation_date"],
        na_values="."
    )
    df = df.rename(columns={"observation_date": "Date"}).set_index("Date")

    logger.info(f"DGS10 fetched. Shape: {df.shape}")
    return df


def check_quality(prices, dgs10, window_days=WINDOW_DAYS):
    """
    최근 window_days 거래일(SPY 기준) 동안 자산별 결측을 점검합니다.

    추정 기간 전체에 가격이 없는 종목은 지원 목록에서 빼야 합니다.
    """
    trading_days = prices["SPY"].dropna().index[-window_days:]
    window = prices.loc[trading_days]

    report = pd.DataFrame({
        "first_date": prices.apply(lambda s: s.first_valid_index()),
        "last_date": prices.apply(lambda s: s.last_valid_index()),
        "missing_in_window": window.isna().sum(),
    })

    dgs10_window = dgs10["DGS10"].reindex(trading_days)
    report.loc["DGS10"] = [
        dgs10["DGS10"].first_valid_index(),
        dgs10["DGS10"].last_valid_index(),
        int(dgs10_window.isna().sum()),
    ]

    report.attrs["window_start"] = trading_days[0]
    report.attrs["window_end"] = trading_days[-1]
    return report


def main():
    parser = argparse.ArgumentParser(
        description="포트폴리오 분석용 가격·금리 원자료 수집"
    )
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=None)
    args = parser.parse_args()

    universe = load_universe()
    prices = fetch_prices(universe.index, args.start, args.end)
    dgs10 = fetch_dgs10(args.start, args.end)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    prices.to_csv(PRICES_PATH)
    dgs10.to_csv(DGS10_PATH)

    report = check_quality(prices, dgs10)
    report.to_csv(QUALITY_PATH)

    logger.info(
        f"Window: {report.attrs['window_start'].date()} ~ "
        f"{report.attrs['window_end'].date()} ({WINDOW_DAYS} days)"
    )
    print(report.to_string())


if __name__ == "__main__":
    main()
