from decimal import Decimal

import pytest

from src.portfolio.stress import compute_stress


def _scenario(factor="market", shock=-0.2, unit="return"):
    return {"id": "test", "name": "Test shock", "factor": factor,
            "shock": shock, "unit": unit}


@pytest.mark.parametrize(
    "factor,shock,unit,loss_pct,loss_usd",
    [
        ("market", -0.2, "return", 20.0, 20_000.0),
        ("rate", 100, "bp", 14.1, 14_100.0),
        ("volatility", 10, "pt", 2.0, 2_000.0),
        ("market", 0, "return", 0.0, 0.0),
        ("market", 0.2, "return", -20.0, -20_000.0),
    ],
)
def test_loss_sign_and_factor_units(factor, shock, unit, loss_pct, loss_usd):
    # Synthetic coefficients isolate the sign and unit conversions.
    betas = [{"ticker": "SPY", "market": 1, "rate": -0.00141, "volatility": -0.002}]

    result = compute_stress(
        {"SPY": 1.0}, 100_000, betas, [_scenario(factor, shock, unit)]
    )[0]

    assert result["loss_pct"] == loss_pct
    assert result["loss_usd"] == loss_usd
    assert result["by_asset"] == [{"ticker": "SPY", "loss_usd": loss_usd}]


@pytest.mark.parametrize(
    "weights,expected_pct,expected_usd,contributions",
    [
        ({"SPY": 0.6, "TLT": 0.4}, 8.0, 8_000.0,
         [{"ticker": "SPY", "loss_usd": 12_000.0},
          {"ticker": "TLT", "loss_usd": -4_000.0}]),
        ({"SPY": 0.2, "TLT": 0.8}, -4.0, -4_000.0,
         [{"ticker": "TLT", "loss_usd": -8_000.0},
          {"ticker": "SPY", "loss_usd": 4_000.0}]),
    ],
)
def test_gains_offset_losses(weights, expected_pct, expected_usd, contributions):
    betas = [{"ticker": "SPY", "market": 1.0}, {"ticker": "TLT", "market": -0.5}]

    result = compute_stress(weights, 100_000, betas, [_scenario()])[0]

    assert result["loss_pct"] == expected_pct
    assert result["loss_usd"] == expected_usd
    assert result["by_asset"] == contributions


def test_total_reconciles_with_rounded_asset_amounts():
    weights = {"SPY": 0.34, "TLT": 0.33, "IEF": 0.33}
    betas = [{"ticker": ticker, "market": 1} for ticker in weights]

    result = compute_stress(weights, 100, betas, [_scenario(shock=-0.001)])[0]

    # Each raw contribution is 0.033 or 0.034 USD, displayed as 0.03 USD.
    assert result["loss_usd"] == 0.09
    assert sum(Decimal(str(a["loss_usd"])) for a in result["by_asset"]) == (
        Decimal(str(result["loss_usd"]))
    )
    assert result["loss_pct"] == 0.1
    assert [a["ticker"] for a in result["by_asset"]] == ["SPY", "IEF", "TLT"]


@pytest.mark.parametrize("shock,expected_usd", [(-0.005, 0.01), (0.005, -0.01)])
def test_half_cent_rounding_preserves_loss_and_gain_signs(shock, expected_usd):
    result = compute_stress(
        {"SPY": 1.0}, 1, [{"ticker": "SPY", "market": 1}], [_scenario(shock=shock)]
    )[0]

    assert result["loss_usd"] == expected_usd
    assert result["by_asset"][0]["loss_usd"] == expected_usd


@pytest.mark.parametrize(
    "betas",
    [
        [],
        [{"ticker": "SPY", "market": 1}, {"ticker": "SPY", "market": 2}],
        [{"ticker": "GLD", "market": 1}],
    ],
)
def test_every_holding_needs_exactly_one_beta(betas):
    with pytest.raises(ValueError, match="정확히 한 번"):
        compute_stress({"SPY": 1.0}, 100_000, betas, [_scenario()])


def test_scenarios_are_evaluated_separately_without_a_combined_total():
    betas = [{"ticker": "SPY", "market": 1, "rate": -0.001, "volatility": -0.002}]
    scenarios = [
        {**_scenario(), "id": "market_test"},
        {**_scenario("rate", 100, "bp"), "id": "rate_test"},
        {**_scenario("volatility", 10, "pt"), "id": "volatility_test"},
    ]

    results = compute_stress({"SPY": 1.0}, 100_000, betas, scenarios)

    assert results == [
        compute_stress({"SPY": 1.0}, 100_000, betas, [scenario])[0]
        for scenario in scenarios
    ]
    assert [row["loss_usd"] for row in results] == [20_000.0, 10_000.0, 2_000.0]
    assert [row["factor"] for row in results] == ["market", "rate", "volatility"]


@pytest.mark.parametrize(
    "factor,shock,unit",
    [("market", -0.2, "return"), ("rate", 100, "bp"), ("volatility", 10, "pt")],
)
def test_scenario_uses_only_its_own_factor_beta(factor, shock, unit):
    beta = {"ticker": "SPY", "market": 1, "rate": -0.001, "volatility": -0.002}
    scenario = _scenario(factor, shock, unit)
    expected = compute_stress({"SPY": 1.0}, 100_000, [beta], [scenario])
    changed = {key: (999 if key not in ("ticker", factor) else value)
               for key, value in beta.items()}

    assert compute_stress({"SPY": 1.0}, 100_000, [changed], [scenario]) == expected
