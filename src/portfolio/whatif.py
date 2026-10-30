def _row(metric, label, unit, current, proposed, digits=2,
         current_detail=None, proposed_detail=None):
    return {
        "metric": metric,
        "label": label,
        "unit": unit,
        "current": current,
        "proposed": proposed,
        "change": round(proposed - current, digits),
        "current_detail": current_detail,
        "proposed_detail": proposed_detail,
    }


def compare_analyses(current, proposed):
    """
    같은 엔진으로 분석한 변경 전후 결과에서 What-if 비교표(기획안 2.15)를 만듭니다.

    current, proposed: /analyze 응답과 같은 구조의 dict.
    손실 지표는 양수 = 손실이므로 change가 양수면 손실이 커진 것입니다.
    """
    cur_asset = current["concentration"]["max_asset"]
    new_asset = proposed["concentration"]["max_asset"]
    cur_sector = current["concentration"]["max_sector"]
    new_sector = proposed["concentration"]["max_sector"]

    rows = [
        _row("max_asset_weight", "최대 자산 비중", "%",
             cur_asset["weight"], new_asset["weight"],
             current_detail=cur_asset["ticker"], proposed_detail=new_asset["ticker"]),
        _row("max_sector_weight", "최대 섹터 비중", "%",
             cur_sector["weight"], new_sector["weight"],
             current_detail=cur_sector["sector"], proposed_detail=new_sector["sector"]),
        _row("volatility", "추정 변동성(연율)", "%",
             current["volatility"], proposed["volatility"]),
        _row("market_beta", "Market 베타", "beta",
             round(current["factor_exposure"]["market"], 4),
             round(proposed["factor_exposure"]["market"], 4), digits=4),
    ]

    new_stress = {s["scenario"]: s for s in proposed["stress"]}
    for s in current["stress"]:
        p = new_stress[s["scenario"]]
        rows.append(_row(f"{s['scenario']}_loss_pct", f"{s['name']} 손실률", "%",
                         s["loss_pct"], p["loss_pct"], digits=4))
        rows.append(_row(f"{s['scenario']}_loss_usd", f"{s['name']} 손실액", "usd",
                         s["loss_usd"], p["loss_usd"]))

    return rows
