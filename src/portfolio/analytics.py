import json
from functools import lru_cache

import numpy as np
import pandas as pd

from src.portfolio.data import WINDOW_DAYS
from src.portfolio.snapshot import SNAPSHOT_META_PATH, SNAPSHOT_PRICES_PATH

TRADING_DAYS_PER_YEAR = 252


@lru_cache(maxsize=1)
def load_window_returns(window_days=WINDOW_DAYS):
    """
    스냅샷 가격으로 추정 기간(최근 window_days 거래일)의 일간 수익률을 만듭니다.
    """
    prices = pd.read_csv(SNAPSHOT_PRICES_PATH, index_col="Date", parse_dates=True)
    return prices.iloc[-(window_days + 1):].pct_change().iloc[1:]


@lru_cache(maxsize=1)
def load_snapshot_meta():
    return json.loads(SNAPSHOT_META_PATH.read_text())


def _pct(x):
    return round(float(x) * 100, 2)


def analyze_portfolio(weights, returns, universe):
    """
    포트폴리오의 숨은 집중위험을 계산합니다.

    weights: {ticker: 비중(소수)}. 결과의 비중·변동성·기여도는 % 단위입니다.
    투자 비중(allocation)과 위험 기여도(risk_contribution)는 다른 개념이므로
    따로 돌려줍니다.
    """
    # 입력 순서와 관계없이 같은 결과가 나오도록 비중 큰 순, 티커 순으로 정렬
    tickers = sorted(weights, key=lambda t: (-weights[t], t))
    w = np.array([weights[t] for t in tickers])

    asset_returns = returns[tickers]
    cov = asset_returns.cov().to_numpy()
    port_var = float(w @ cov @ w)
    volatility = np.sqrt(port_var * TRADING_DAYS_PER_YEAR)

    # 위험 기여도 비율: w_i (Σw)_i / (wᵀΣw), 합계 100%
    risk_share = w * (cov @ w) / port_var

    meta = universe.loc[tickers]
    allocation = [
        {
            "ticker": t,
            "name": meta.at[t, "name"],
            "sector": meta.at[t, "sector"],
            "weight": _pct(wt),
        }
        for t, wt in zip(tickers, w)
    ]

    sector_weights = pd.Series(w, index=meta["sector"].to_numpy()).groupby(level=0).sum()
    sector_order = sorted(sector_weights.index, key=lambda s: (-sector_weights[s], s))
    sector = [{"sector": s, "weight": _pct(sector_weights[s])} for s in sector_order]

    corr = asset_returns.corr().round(3)

    return {
        "allocation": allocation,
        "sector": sector,
        "concentration": {
            "max_asset": {"ticker": tickers[0], "weight": _pct(w[0])},
            "max_sector": sector[0],
        },
        "correlation": {
            "tickers": tickers,
            "matrix": corr.to_numpy().tolist(),
        },
        "volatility": _pct(volatility),
        "risk_contribution": [
            {"ticker": t, "share": _pct(s)} for t, s in zip(tickers, risk_share)
        ],
    }
