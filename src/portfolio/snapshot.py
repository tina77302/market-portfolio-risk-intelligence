import json
import logging
from pathlib import Path

import pandas as pd

from src.portfolio.data import DGS10_PATH, PRICES_PATH, WINDOW_DAYS
from src.portfolio.universe import load_universe

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

PORTFOLIO_DIR = Path(__file__).resolve().parents[2] / "data" / "portfolio"
SNAPSHOT_PRICES_PATH = PORTFOLIO_DIR / "prices.csv"
SNAPSHOT_FACTORS_PATH = PORTFOLIO_DIR / "factors.csv"
SNAPSHOT_META_PATH = PORTFOLIO_DIR / "snapshot_meta.json"


def find_as_of(prices, dgs10):
    """
    모든 자산·VIX·DGS10 값이 함께 있는 가장 최근 날짜를 기준일로 정합니다.

    FRED 금리는 주가보다 하루 이상 늦게 올라오므로,
    가장 최근 거래일이 아니라 세 데이터가 모두 있는 날을 씁니다.
    """
    combined = prices.join(dgs10["DGS10"], how="left")
    return combined.dropna().index[-1]


def build_snapshot(prices, dgs10, tickers, window_days=WINDOW_DAYS):
    """
    기준일까지의 SPY 거래일만 남긴 가격·팩터 스냅샷을 만듭니다.

    수정종가는 새 배당이 생길 때마다 과거 값이 다시 계산되므로,
    시연과 검증은 이 스냅샷으로만 합니다.
    DGS10 결측(채권시장 휴장일)은 그대로 둡니다.
    """
    tickers = list(tickers)
    as_of = find_as_of(prices[tickers + ["VIX"]], dgs10)

    trading_days = prices.index[
        prices["SPY"].notna() & (prices.index <= as_of)
    ]

    snapshot_prices = prices.loc[trading_days, tickers].round(4)
    snapshot_factors = pd.DataFrame({
        "VIX": prices.loc[trading_days, "VIX"].round(2),
        "DGS10": dgs10["DGS10"].reindex(trading_days),
    })

    window = trading_days[-window_days:]
    meta = {
        "as_of": str(as_of.date()),
        "start": str(trading_days[0].date()),
        "window_start": str(window[0].date()),
        "window_end": str(window[-1].date()),
        "window_days": len(window),
        "price_source": "Yahoo Finance adjusted close (auto_adjust)",
        "rate_source": "FRED DGS10 (10-Year Treasury, %)",
        "vol_source": "Yahoo Finance ^VIX close",
    }
    return snapshot_prices, snapshot_factors, meta


def main():
    universe = load_universe()
    prices = pd.read_csv(PRICES_PATH, index_col="Date", parse_dates=True)
    dgs10 = pd.read_csv(DGS10_PATH, index_col="Date", parse_dates=True)

    snapshot_prices, snapshot_factors, meta = build_snapshot(
        prices, dgs10, universe.index
    )

    PORTFOLIO_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_prices.to_csv(SNAPSHOT_PRICES_PATH)
    snapshot_factors.to_csv(SNAPSHOT_FACTORS_PATH)
    SNAPSHOT_META_PATH.write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n"
    )

    logger.info(
        f"Snapshot as of {meta['as_of']}: "
        f"{snapshot_prices.shape[0]} days x {snapshot_prices.shape[1]} assets, "
        f"window {meta['window_start']} ~ {meta['window_end']}"
    )


if __name__ == "__main__":
    main()
