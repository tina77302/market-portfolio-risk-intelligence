"""Read-only HTTP smoke check for the existing frozen-snapshot Portfolio demo."""
import argparse
import json
import math
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def request(base, path, body=None):
    payload = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"} if payload else {}
    query = Request(base + path, data=payload, headers=headers)
    try:
        with urlopen(query, timeout=15) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, json.loads(error.read())


def check(base):
    expected = json.loads((ROOT / "examples/portfolio/expected.json").read_text())
    inputs = {
        name: json.loads((ROOT / f"examples/portfolio/{name}.json").read_text())
        for name in ("before", "after")
    }
    status, health = request(base, "/health")
    assert status == 200 and health["as_of"] == expected["as_of"]
    status, universe = request(base, "/api/portfolio/universe")
    assert status == 200 and len(universe["assets"]) >= 10
    status, scenarios = request(base, "/api/portfolio/scenarios")
    assert status == 200 and len(scenarios["scenarios"]) == 3
    analyses = {}
    for name, body in inputs.items():
        status, analysis = request(base, "/api/portfolio/analyze", body)
        assert status == 200
        assert analysis["window"] == expected["window"]
        assert len(analysis["factor_exposure"]["by_asset"]) == len(body["holdings"])
        assert len(analysis["correlation"]["matrix"]) == len(body["holdings"])
        assert math.isclose(sum(row["share"] for row in analysis["risk_contribution"]), 100, abs_tol=.02)
        assert len(analysis["stress"]) == 3
        for scenario in analysis["stress"]:
            assert math.isclose(
                sum(row["loss_usd"] for row in scenario["by_asset"]), scenario["loss_usd"], abs_tol=.01
            )
        analyses[name] = {
            "volatility": analysis["volatility"],
            "nvda_weight": next(row["weight"] for row in analysis["allocation"] if row["ticker"] == "NVDA"),
            "nvda_risk_share": next(
                row["share"] for row in analysis["risk_contribution"] if row["ticker"] == "NVDA"
            ),
        }
        stress = {row["scenario"]: row for row in analysis["stress"]}
        analyses[name].update({
            "equity_selloff_loss_pct": stress["equity_selloff"]["loss_pct"],
            "rate_shock_loss_pct": stress["rate_shock"]["loss_pct"],
            "rate_shock_significant": stress["rate_shock"]["significant"],
        })
        for metric, value in expected[name].items():
            assert math.isclose(analyses[name][metric], value, abs_tol=.02), (name, metric)
    status, comparison = request(
        base, "/api/portfolio/compare", {"current": inputs["before"], "proposed": inputs["after"]}
    )
    assert status == 200
    row = next(row for row in comparison["comparison"] if row["metric"] == "volatility")
    assert math.isclose(row["current"], expected["before"]["volatility"], abs_tol=.02)
    assert math.isclose(row["proposed"], expected["after"]["volatility"], abs_tol=.02)
    invalid_inputs = [
        {"holdings": [{"ticker": "AAPL", "weight": 90}], "value_usd": 100000},
        {"holdings": [{"ticker": "NOPE", "weight": 100}], "value_usd": 100000},
        {"holdings": inputs["before"]["holdings"], "value_usd": -1},
    ]
    for body in invalid_inputs:
        status, _ = request(base, "/api/portfolio/analyze", body)
        assert status == 422
    return {
        "health": health,
        "universe_assets": len(universe["assets"]),
        "analysis": analyses,
        "stress_scenarios": 3,
        "comparison_rows": len(comparison["comparison"]),
        "invalid_requests": "3 rejected with 422",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    print(json.dumps(check(args.api_url.rstrip("/")), indent=2))


if __name__ == "__main__":
    main()
