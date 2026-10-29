import numpy as np
import pandas as pd
import pytest

from src.portfolio.factors import (
    build_factor_moves,
    estimate_betas,
    portfolio_exposure,
)


@pytest.fixture
def market_data():
    rng = np.random.default_rng(1)
    n = 301
    days = pd.bdate_range("2024-01-01", periods=n)

    spy_ret = rng.normal(0, 0.01, n)
    rate_bp = rng.normal(0, 5, n)
    vix_pt = rng.normal(0, 1, n)
    noise = rng.normal(0, 0.001, n)

    # 알려진 베타로 만든 자산: LEV는 시장 1.5배, BOND는 금리 1bp당 -0.1%
    lev_ret = 1.5 * spy_ret + noise
    bond_ret = -0.001 * rate_bp + noise

    prices = pd.DataFrame({
        "SPY": 100 * np.cumprod(1 + spy_ret),
        "LEV": 100 * np.cumprod(1 + lev_ret),
        "BOND": 100 * np.cumprod(1 + bond_ret),
    }, index=days)
    factors = pd.DataFrame({
        "DGS10": 4 + np.cumsum(rate_bp) / 100,
        "VIX": 20 + np.cumsum(vix_pt),
    }, index=days)
    return prices, factors


def test_betas_recover_known_sensitivities(market_data):
    prices, factors = market_data
    asset_returns, factor_moves = build_factor_moves(prices, factors, window_days=300)

    betas = estimate_betas(asset_returns, factor_moves)

    assert betas.at["SPY", "market"] == pytest.approx(1.0)
    assert betas.at["LEV", "market"] == pytest.approx(1.5, abs=0.02)
    assert betas.at["BOND", "rate"] == pytest.approx(-0.001, abs=0.00005)
    assert betas.at["LEV", "market_r2"] > 0.95
    assert betas.at["BOND", "market_r2"] < 0.05


def test_missing_rate_day_drops_only_from_rate_regression(market_data):
    prices, factors = market_data
    factors.iloc[150, factors.columns.get_loc("DGS10")] = np.nan
    asset_returns, factor_moves = build_factor_moves(prices, factors, window_days=300)

    betas = estimate_betas(asset_returns, factor_moves)

    # 결측일 당일과 다음 날의 금리 변화가 함께 빠짐
    assert betas.at["BOND", "rate_n"] == 298
    assert betas.at["BOND", "market_n"] == 300


def test_portfolio_exposure_is_weighted_sum_in_allocation_order():
    betas = pd.DataFrame(
        {"market": [1.2, -0.1], "rate": [-0.0002, -0.0014], "volatility": [-0.004, 0.0002]},
        index=pd.Index(["AAPL", "TLT"], name="ticker"),
    )

    exposure = portfolio_exposure({"TLT": 0.4, "AAPL": 0.6}, betas)

    assert exposure["market"] == pytest.approx(0.6 * 1.2 + 0.4 * -0.1)
    assert exposure["rate"] == pytest.approx(0.6 * -0.0002 + 0.4 * -0.0014)
    assert [a["ticker"] for a in exposure["by_asset"]] == ["AAPL", "TLT"]
    assert exposure["by_asset"][1]["market"] == -0.1
