import numpy as np
import pandas as pd
import pytest

from src.portfolio.analytics import analyze_portfolio


@pytest.fixture
def returns():
    rng = np.random.default_rng(0)
    return pd.DataFrame(
        rng.normal(0, 0.01, size=(500, 3)),
        columns=["A", "B", "C"],
    )


@pytest.fixture
def universe():
    return pd.DataFrame(
        {
            "name": ["Asset A", "Asset B", "Asset C"],
            "sector": ["Tech", "Tech", "Treasury"],
        },
        index=pd.Index(["A", "B", "C"], name="ticker"),
    )


def test_single_asset_volatility_equals_asset_volatility(returns, universe):
    result = analyze_portfolio({"A": 1.0}, returns, universe)

    expected = returns["A"].std() * np.sqrt(252) * 100
    assert result["volatility"] == pytest.approx(expected, abs=0.01)
    assert result["risk_contribution"] == [{"ticker": "A", "share": 100.0}]


def test_volatility_matches_hand_formula(returns, universe):
    weights = {"A": 0.5, "B": 0.3, "C": 0.2}
    cov = returns.cov()
    variance = sum(
        weights[i] * weights[j] * cov.loc[i, j]
        for i in weights for j in weights
    )

    result = analyze_portfolio(weights, returns, universe)

    assert result["volatility"] == pytest.approx(
        np.sqrt(variance * 252) * 100, abs=0.01
    )


def test_sector_and_concentration(returns, universe):
    result = analyze_portfolio({"A": 0.5, "B": 0.3, "C": 0.2}, returns, universe)

    assert result["sector"] == [
        {"sector": "Tech", "weight": 80.0},
        {"sector": "Treasury", "weight": 20.0},
    ]
    assert result["concentration"]["max_asset"] == {"ticker": "A", "weight": 50.0}
    assert result["concentration"]["max_sector"] == {"sector": "Tech", "weight": 80.0}


def test_risk_shares_sum_to_100(returns, universe):
    result = analyze_portfolio({"A": 0.5, "B": 0.3, "C": 0.2}, returns, universe)

    total = sum(r["share"] for r in result["risk_contribution"])
    assert total == pytest.approx(100, abs=0.05)


def test_input_order_does_not_change_result(returns, universe):
    first = analyze_portfolio({"A": 0.5, "B": 0.3, "C": 0.2}, returns, universe)
    second = analyze_portfolio({"C": 0.2, "A": 0.5, "B": 0.3}, returns, universe)

    assert first == second


def test_correlation_matrix_is_square_with_unit_diagonal(returns, universe):
    result = analyze_portfolio({"A": 0.5, "B": 0.3, "C": 0.2}, returns, universe)

    matrix = np.array(result["correlation"]["matrix"])
    assert matrix.shape == (3, 3)
    assert np.allclose(np.diag(matrix), 1.0)
