import csv
import json
import math
import statistics

import pytest

from src.portfolio import demo
from src.portfolio.snapshot import SNAPSHOT_PRICES_PATH


@pytest.mark.parametrize("name", ["before", "after"])
def test_demo_matches_reference_and_direct_daily_portfolio_returns(name):
    summary = demo.run_demo()
    expected = json.loads(demo.EXPECTED_PATH.read_text())
    assert summary == expected

    request = json.loads((demo.DEMO_DIR / f"{name}.json").read_text())
    weights = {h["ticker"]: h["weight"] / 100 for h in request["holdings"]}
    with SNAPSHOT_PRICES_PATH.open() as source:
        prices = list(csv.DictReader(source))[-757:]
    # Recompute from daily portfolio returns without the covariance-matrix helper.
    portfolio_returns = []
    nvda_returns = []
    for previous, current in zip(prices, prices[1:]):
        returns = {t: float(current[t]) / float(previous[t]) - 1 for t in weights}
        portfolio_returns.append(sum(weights[t] * returns[t] for t in weights))
        nvda_returns.append(returns["NVDA"])
    variance = statistics.variance(portfolio_returns)
    share = weights["NVDA"] * statistics.covariance(nvda_returns, portfolio_returns) / variance

    assert summary["window"] == {
        "start": prices[1]["Date"], "end": prices[-1]["Date"], "days": 756,
    }
    assert summary[name]["volatility"] == round(math.sqrt(variance * 252) * 100, 2)
    assert summary[name]["nvda_risk_share"] == round(share * 100, 2)
    assert summary[name]["nvda_weight"] == pytest.approx(weights["NVDA"] * 100)


def test_demo_moves_thirty_percent_without_changing_portfolio_value():
    requests = {name: json.loads((demo.DEMO_DIR / f"{name}.json").read_text())
                for name in ("before", "after")}
    weights = {name: {h["ticker"]: h["weight"] for h in request["holdings"]}
               for name, request in requests.items()}

    assert requests["before"]["value_usd"] == requests["after"]["value_usd"] == 100_000
    assert sum(weights["before"].values()) == sum(weights["after"].values()) == 100
    for ticker, weight in weights["before"].items():
        assert weights["after"][ticker] == pytest.approx(weight * 0.7)
    assert {t: w for t, w in weights["after"].items() if t not in weights["before"]} == {
        "TLT": 10, "GLD": 10, "XLV": 10,
    }


def test_demo_check_fails_if_recorded_results_drift(tmp_path, monkeypatch):
    expected = json.loads(demo.EXPECTED_PATH.read_text())
    expected["before"]["volatility"] = 0
    changed_reference = tmp_path / "expected.json"
    changed_reference.write_text(json.dumps(expected))
    monkeypatch.setattr(demo, "EXPECTED_PATH", changed_reference)
    monkeypatch.setattr("sys.argv", ["portfolio-demo", "--check"])

    with pytest.raises(SystemExit) as error:
        demo.main()

    assert error.value.code == 1
