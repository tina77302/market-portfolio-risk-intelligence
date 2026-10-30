import json

import pytest
from fastapi.testclient import TestClient

from src.portfolio.demo import DEMO_DIR, EXPECTED_PATH
from src.portfolio.server import app

client = TestClient(app)


def _demo(name):
    return json.loads((DEMO_DIR / f"{name}.json").read_text())


def _compare(current, proposed):
    return client.post(
        "/api/portfolio/compare", json={"current": current, "proposed": proposed}
    )


def test_compare_returns_both_analyses_and_plan_rows():
    response = _compare(_demo("before"), _demo("after"))

    assert response.status_code == 200
    body = response.json()
    rows = {r["metric"]: r for r in body["comparison"]}
    assert list(rows) == [
        "max_asset_weight", "max_sector_weight", "volatility", "market_beta",
        "equity_selloff_loss_pct", "equity_selloff_loss_usd",
        "rate_shock_loss_pct", "rate_shock_loss_usd",
        "volatility_shock_loss_pct", "volatility_shock_loss_usd",
    ]
    assert body["current"]["allocation"][0]["ticker"] == "AAPL"
    assert body["proposed"]["allocation"][-1]["ticker"] in {"TLT", "GLD", "XLV"}


def test_compare_rows_match_each_side_of_the_analysis():
    body = _compare(_demo("before"), _demo("after")).json()
    rows = {r["metric"]: r for r in body["comparison"]}
    expected = json.loads(EXPECTED_PATH.read_text())

    vol = rows["volatility"]
    assert (vol["current"], vol["proposed"]) == (
        expected["before"]["volatility"], expected["after"]["volatility"]
    )
    assert vol["change"] == pytest.approx(vol["proposed"] - vol["current"], abs=0.01)

    equity = next(s for s in body["proposed"]["stress"] if s["scenario"] == "equity_selloff")
    assert rows["equity_selloff_loss_usd"]["proposed"] == equity["loss_usd"]
    assert rows["max_sector_weight"]["current_detail"] == "Information Technology"


def test_moving_into_bonds_and_gold_trades_equity_loss_for_rate_loss():
    rows = {r["metric"]: r for r in _compare(_demo("before"), _demo("after")).json()["comparison"]}

    assert rows["volatility"]["change"] < 0
    assert rows["equity_selloff_loss_pct"]["change"] < 0
    assert rows["volatility_shock_loss_pct"]["change"] < 0
    assert rows["rate_shock_loss_pct"]["change"] > 0


def test_compare_requires_the_same_portfolio_value():
    proposed = _demo("after") | {"value_usd": 50_000}

    assert _compare(_demo("before"), proposed).status_code == 422


def test_compare_validates_each_portfolio():
    proposed = _demo("after")
    proposed["holdings"][0]["weight"] -= 1  # 합계 99%

    assert _compare(_demo("before"), proposed).status_code == 422
