import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.portfolio import api as portfolio_api
from src.portfolio.api import router
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
    assert body["factor_exposure"] is None
    assert body["stress"] is None


def test_spy_only_portfolio_is_fully_concentrated():
    body = _analyze([{"ticker": "spy", "weight": 100}]).json()

    assert body["sector"] == [{"sector": "Broad Equity", "weight": 100.0}]
    assert body["risk_contribution"] == [{"ticker": "SPY", "share": 100.0}]


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
    original_analyze = portfolio_api.analyze_portfolio

    def analyze_with_factors(weights, returns, universe):
        result = original_analyze(weights, returns, universe)
        result["factor_exposure"] = exposure
        return result

    monkeypatch.setattr(portfolio_api, "analyze_portfolio", analyze_with_factors)

    response = _analyze([
        {"ticker": "AAPL", "weight": 60},
        {"ticker": "TLT", "weight": 40},
    ])

    assert response.status_code == 200
    assert response.json()["factor_exposure"] == exposure


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
