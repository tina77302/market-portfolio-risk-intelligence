from decimal import Decimal, ROUND_HALF_UP


def compute_stress(weights, value_usd, asset_betas, scenarios):
    """베타와 충격을 손실로 변환합니다. 양수는 손실, 음수는 이익입니다.

    weights와 베타의 수익률 단위는 소수이며, 충격은 시나리오의 단위를 따릅니다.
    자산별 금액을 센트로 반올림한 뒤 합산하고, 손실률은 별도로 계산합니다.
    각 시나리오는 해당 팩터의 베타만 사용합니다. 시나리오 간 합산은 하지 않습니다.
    """
    betas = {asset["ticker"]: asset for asset in asset_betas}
    if len(betas) != len(asset_betas) or set(betas) != set(weights):
        raise ValueError("보유 자산마다 베타가 정확히 한 번씩 필요합니다.")

    tickers = sorted(weights, key=lambda ticker: (-weights[ticker], ticker))
    value = Decimal(str(value_usd))
    results = []
    for scenario in scenarios:
        shock = Decimal(str(scenario["shock"]))
        factor = scenario["factor"]
        loss_rate = Decimal(0)
        loss_usd = Decimal(0)
        by_asset = []
        for ticker in tickers:
            asset_loss_rate = (
                -Decimal(str(weights[ticker]))
                * Decimal(str(betas[ticker][factor]))
                * shock
            )
            asset_loss_usd = (value * asset_loss_rate).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            loss_rate += asset_loss_rate
            loss_usd += asset_loss_usd
            by_asset.append({"ticker": ticker, "loss_usd": float(asset_loss_usd)})

        results.append({
            "scenario": scenario["id"],
            "name": scenario["name"],
            "factor": factor,
            "shock": scenario["shock"],
            "unit": scenario["unit"],
            "loss_pct": float((loss_rate * 100).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )),
            "loss_usd": float(loss_usd),
            "by_asset": by_asset,
        })

    return results
