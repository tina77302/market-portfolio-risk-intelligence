import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.portfolio import api as portfolio_api
from src.portfolio.api import router
from src.portfolio.demo import DEMO_DIR, EXPECTED_PATH
from src.portfolio.universe import load_universe

app = FastAPI()
app.include_router(router)
client = TestClient(app)


def _analyze(holdings, value_usd=100_000):
    return client.post(
        "/api/portfolio/analyze",
        json={"holdings": holdings, "value_usd": value_usd},
    )


def test_analyze_returns_hidden_risk():
    response = _analyze([
        {"ticker": "AAPL", "weight": 60},
        {"ticker": "TLT", "weight": 40},
    ])

    assert response.status_code == 200
    body = response.json()
    assert body["value_usd"] == 100_000
    assert body["window"]["days"] == 756
    assert body["concentration"]["max_asset"] == {"ticker": "AAPL", "weight": 60.0}
    assert body["correlation"]["tickers"] == ["AAPL", "TLT"]
    assert body["volatility"] > 0
    assert [a["ticker"] for a in body["factor_exposure"]["by_asset"]] == ["AAPL", "TLT"]
    assert [s["scenario"] for s in body["stress"]] == [
        "equity_selloff", "rate_shock", "volatility_shock"
    ]


def test_spy_only_portfolio_is_fully_concentrated():
    body = _analyze([{"ticker": "spy", "weight": 100}]).json()

    assert body["sector"] == [{"sector": "Broad Equity", "weight": 100.0}]
    assert body["risk_contribution"] == [{"ticker": "SPY", "share": 100.0}]


def test_etf_sector_weights_explain_that_holdings_are_not_expanded():
    response = _analyze([
        {"ticker": "AAPL", "weight": 50},
        {"ticker": "QQQ", "weight": 50},
    ])

    assert response.status_code == 200
    body = response.json()
    assert body["sector"] == [
        {"sector": "Broad Equity", "weight": 50.0},
        {"sector": "Information Technology", "weight": 50.0},
    ]
    method = body["sector_methodology"]
    assert method == client.get("/api/portfolio/universe").json()["sector_methodology"]
    assert method["classification"] == "asset_level"
    assert method["etf_lookthrough"] is False
    assert "ETF 내부 보유종목 미반영" in method["label"]
    assert method["limitations"]


@pytest.mark.parametrize("name", ["before", "after"])
def test_saved_demo_requests_work_through_http_api(name):
    request = json.loads((DEMO_DIR / f"{name}.json").read_text())
    expected = json.loads(EXPECTED_PATH.read_text())
    response = client.post("/api/portfolio/analyze", json=request)

    assert response.status_code == 200
    body = response.json()
    assert body["as_of"] == expected["as_of"]
    assert body["window"] == expected["window"]
    assert body["volatility"] == expected[name]["volatility"]
    assert next(a["share"] for a in body["risk_contribution"] if a["ticker"] == "NVDA") == (
        expected[name]["nvda_risk_share"]
    )


def test_analyze_preserves_asset_factor_exposure(monkeypatch):
    # Synthetic coefficients test the response contract, not estimated betas.
    exposure = {
        "market": 0.62,
        "rate": -0.00068,
        "volatility": -0.00052,
        "by_asset": [
            {"ticker": "AAPL", "market": 1.1, "rate": -0.0002, "volatility": -0.001},
            {"ticker": "TLT", "market": -0.1, "rate": -0.0014, "volatility": 0.0002},
        ],
    }
    monkeypatch.setattr(
        portfolio_api, "portfolio_exposure", lambda weights, betas: exposure
    )

    response = _analyze([
        {"ticker": "AAPL", "weight": 60},
        {"ticker": "TLT", "weight": 40},
    ])

    assert response.status_code == 200
    assert response.json()["factor_exposure"] == exposure
    stress = {s["scenario"]: s for s in response.json()["stress"]}
    assert stress["equity_selloff"]["loss_pct"] == 14.4398
    assert stress["equity_selloff"]["loss_usd"] == 14_439.8
    assert stress["equity_selloff"]["by_asset"] == [
        {"ticker": "AAPL", "loss_usd": 15_371.4},
        {"ticker": "TLT", "loss_usd": -931.6},
    ]
    assert stress["rate_shock"]["loss_usd"] == 4_692.0
    assert stress["volatility_shock"]["by_asset"][1]["loss_usd"] == -394.16
    assert {key: row["factor"] for key, row in stress.items()} == {
        "equity_selloff": "market",
        "rate_shock": "rate",
        "volatility_shock": "volatility",
    }


def test_spy_only_stress_equals_the_market_shock():
    body = _analyze([{"ticker": "SPY", "weight": 100}]).json()
    shock = client.get("/api/portfolio/scenarios").json()["scenarios"][0]["shock"]
    equity = next(s for s in body["stress"] if s["scenario"] == "equity_selloff")

    assert body["factor_exposure"]["market"] == pytest.approx(1.0)
    assert equity["loss_pct"] == pytest.approx(-shock * 100, abs=1e-4)
    assert equity["loss_usd"] == pytest.approx(-shock * 100_000, abs=0.01)


def test_tlt_only_portfolio_loses_when_rates_rise():
    body = _analyze([{"ticker": "TLT", "weight": 100}]).json()
    rate = next(s for s in body["stress"] if s["scenario"] == "rate_shock")

    assert body["factor_exposure"]["rate"] < 0
    assert rate["loss_pct"] > 0


def test_methodology_is_consistent_across_endpoints():
    analysis_response = _analyze([{"ticker": "SPY", "weight": 100}])
    scenario_response = client.get("/api/portfolio/scenarios")

    assert analysis_response.status_code == scenario_response.status_code == 200
    analysis = analysis_response.json()
    scenarios = scenario_response.json()
    method = analysis["methodology"]
    assert method == scenarios["methodology"]
    assert method["regression"] == "separate_univariate"
    assert method["beta_frequency"] == "daily"
    assert method["shock_horizon_days"] == scenarios["horizon_days"] == 10
    assert method["approximation"] == "linear_beta_times_shock"
    assert method["scenarios_additive"] is False
    assert method["is_forecast"] is False
    assert len(method["limitations"]) == 3


def test_openapi_documents_asset_factor_exposure():
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    exposure = schemas["FactorExposure"]
    asset = schemas["AssetFactorExposure"]

    assert "by_asset" in exposure["required"]
    assert exposure["properties"]["by_asset"]["items"]["$ref"] == (
        "#/components/schemas/AssetFactorExposure"
    )
    assert set(asset["required"]) == {"ticker", "market", "rate", "volatility"}


ELEVEN = [{"ticker": t, "weight": 100 / 11} for t in load_universe().index[:11]]


@pytest.mark.parametrize(
    "holdings",
    [
        [{"ticker": "AAPL", "weight": 99}],
        ELEVEN,
        [{"ticker": "ZZZZ", "weight": 100}],
        [{"ticker": "AAPL", "weight": 50}, {"ticker": "aapl", "weight": 50}],
        [{"ticker": "AAPL", "weight": 0}, {"ticker": "MSFT", "weight": 100}],
        [],
    ],
    ids=["sum-99", "eleven-assets", "unknown-ticker", "duplicate", "zero-weight", "empty"],
)
def test_invalid_portfolio_is_rejected(holdings):
    assert _analyze(holdings).status_code == 422


def test_value_must_be_positive():
    assert _analyze([{"ticker": "SPY", "weight": 100}], value_usd=0).status_code == 422


@pytest.mark.parametrize(
    "value_usd",
    ["Infinity", "+Infinity", "-Infinity", "NaN", "1e309", "-1e309"],
)
def test_non_finite_value_is_rejected(value_usd):
    response = _analyze([{"ticker": "SPY", "weight": 100}], value_usd=value_usd)

    assert response.status_code == 422
    assert any(
        error["loc"] == ["body", "value_usd"]
        for error in response.json()["detail"]
    )


def test_universe_and_scenarios_endpoints():
    assets = client.get("/api/portfolio/universe").json()["assets"]
    scenarios = client.get("/api/portfolio/scenarios").json()["scenarios"]

    assert len(assets) == len(load_universe())
    assert [s["id"] for s in scenarios] == [
        "equity_selloff", "rate_shock", "volatility_shock"
    ]
