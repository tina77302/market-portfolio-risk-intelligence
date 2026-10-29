import numpy as np
import pandas as pd

from src.portfolio.scenarios import compute_scenarios
from src.portfolio.snapshot import build_snapshot, find_as_of


def _sample_data(n=30):
    days = pd.bdate_range("2024-01-01", periods=n)
    prices = pd.DataFrame({
        "SPY": np.linspace(100, 110, n),
        "TLT": np.linspace(90, 95, n),
        "VIX": np.full(n, 15.0),
    }, index=days)
    dgs10 = pd.DataFrame({"DGS10": np.full(n, 4.0)}, index=days)
    return prices, dgs10


def test_as_of_is_last_day_with_every_series():
    prices, dgs10 = _sample_data()
    dgs10.iloc[-2:] = np.nan

    assert find_as_of(prices, dgs10) == prices.index[-3]


def test_snapshot_stops_at_as_of_and_keeps_rate_gaps():
    prices, dgs10 = _sample_data()
    dgs10.iloc[-1] = np.nan
    dgs10.iloc[5] = np.nan

    snap_prices, snap_factors, meta = build_snapshot(
        prices, dgs10, ["SPY", "TLT"], window_days=20
    )

    assert snap_prices.index[-1] == prices.index[-2]
    assert meta["as_of"] == str(prices.index[-2].date())
    assert meta["window_days"] == 20
    assert np.isnan(snap_factors["DGS10"].iloc[5])


def test_scenarios_pick_worst_ten_day_moves():
    prices, dgs10 = _sample_data()
    prices.iloc[20:, prices.columns.get_loc("SPY")] *= 0.8
    prices.iloc[15:, prices.columns.get_loc("VIX")] = 40.0
    dgs10.iloc[12:] = 4.5
    factors = pd.DataFrame({"VIX": prices["VIX"], "DGS10": dgs10["DGS10"]})

    scenarios = {s["id"]: s for s in compute_scenarios(prices, factors)}

    assert scenarios["equity_selloff"]["shock"] < -0.15
    assert scenarios["rate_shock"]["shock"] == 50.0
    assert scenarios["volatility_shock"]["shock"] == 25.0

    reference = scenarios["volatility_shock"]["reference"]
    assert pd.bdate_range(reference["start"], reference["end"]).size == 11
