import json
import logging
from pathlib import Path

import pandas as pd

from src.portfolio.snapshot import (
    SNAPSHOT_FACTORS_PATH,
    SNAPSHOT_META_PATH,
    SNAPSHOT_PRICES_PATH,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

SCENARIOS_PATH = (
    Path(__file__).resolve().parents[2]
    / "data" / "portfolio" / "scenarios.json"
)

# 시장 조기경보 모델의 예측 구간(Target_10D)과 같은 10거래일
HORIZON_DAYS = 10


def describe_methodology(horizon_days=HORIZON_DAYS):
    """팩터·스트레스 결과의 공통 해석 규칙을 반환합니다."""
    return {
        "regression": "separate_univariate",
        "beta_frequency": "daily",
        "shock_horizon_days": horizon_days,
        "approximation": "linear_beta_times_shock",
        "scenarios_additive": False,
        "is_forecast": False,
        "limitations": [
            "각 베타는 팩터를 하나씩 따로 회귀한 민감도이며, 다른 팩터의 영향을 통제한 순수 효과가 아닙니다.",
            "팩터 간 상관으로 같은 시장 움직임이 중복 반영될 수 있으므로 시나리오별 손실은 합산하지 않습니다.",
            f"일별 베타에 {horizon_days}거래일 충격을 곱한 선형 근사이며, 미래 손실이나 발생 확률의 예측이 아닙니다.",
        ],
    }


# shock 단위: return = 소수 수익률, bp = 금리 변화, pt = VIX 포인트 변화
SCENARIOS = [
    {
        "id": "equity_selloff",
        "name": "Equity Sell-off",
        "definition": "주식시장 급락",
        "factor": "market",
        "series": "SPY",
        "unit": "return",
        "worst": "min",
        "rule": "스냅샷 기간 중 SPY 10거래일 수익률의 최저값",
        "pnl_method": "손실률(%) = -포트폴리오 Market 베타 × 충격 × 100 (양수=손실, 음수=이익)",
    },
    {
        "id": "rate_shock",
        "name": "Interest Rate Shock",
        "definition": "10년 국채금리 급등",
        "factor": "rate",
        "series": "DGS10",
        "unit": "bp",
        "worst": "max",
        "rule": "스냅샷 기간 중 DGS10 10거래일 변화(bp)의 최고값",
        "pnl_method": "손실률(%) = -포트폴리오 Rate 베타(bp당) × 충격 × 100 (양수=손실, 음수=이익)",
    },
    {
        "id": "volatility_shock",
        "name": "Volatility Shock",
        "definition": "시장 변동성 급등",
        "factor": "volatility",
        "series": "VIX",
        "unit": "pt",
        "worst": "max",
        "rule": "스냅샷 기간 중 VIX 10거래일 변화(pt)의 최고값",
        "pnl_method": "손실률(%) = -포트폴리오 Volatility 베타(pt당) × 충격 × 100 (양수=손실, 음수=이익)",
    },
]


def horizon_moves(prices, factors, horizon=HORIZON_DAYS):
    """
    시나리오별 연결 지표의 horizon 거래일 변화량을 계산합니다.

    DGS10 휴장일은 직전 금리 수준을 이어 써서 변화량을 구합니다.
    """
    dgs10 = factors["DGS10"].ffill()
    return pd.DataFrame({
        "SPY": prices["SPY"] / prices["SPY"].shift(horizon) - 1,
        "DGS10": (dgs10 - dgs10.shift(horizon)) * 100,
        "VIX": factors["VIX"] - factors["VIX"].shift(horizon),
    })


def compute_scenarios(prices, factors, horizon=HORIZON_DAYS):
    """
    과거 최악의 horizon 거래일 움직임을 충격 크기로 정하고,
    그 움직임이 일어난 구간을 역사적 근거로 함께 기록합니다.
    """
    moves = horizon_moves(prices, factors, horizon)
    days = moves.index

    scenarios = []
    for spec in SCENARIOS:
        series = moves[spec["series"]].dropna()
        end = series.idxmin() if spec["worst"] == "min" else series.idxmax()
        start = days[days.get_loc(end) - horizon]

        scenario = {k: v for k, v in spec.items() if k not in ("series", "worst")}
        scenario["shock"] = round(float(series.loc[end]), 4)
        scenario["reference"] = {
            "start": str(start.date()),
            "end": str(end.date()),
        }
        scenarios.append(scenario)

    return scenarios


def main():
    prices = pd.read_csv(SNAPSHOT_PRICES_PATH, index_col="Date", parse_dates=True)
    factors = pd.read_csv(SNAPSHOT_FACTORS_PATH, index_col="Date", parse_dates=True)
    meta = json.loads(SNAPSHOT_META_PATH.read_text())

    output = {
        "as_of": meta["as_of"],
        "lookback_start": meta["start"],
        "horizon_days": HORIZON_DAYS,
        "note": "사전에 정한 충격 가정에 따른 추정치이며 미래 손실 예측이 아닙니다.",
        "methodology": describe_methodology(),
        "scenarios": compute_scenarios(prices, factors),
    }
    SCENARIOS_PATH.write_text(
        json.dumps(output, indent=2, ensure_ascii=False) + "\n"
    )

    for s in output["scenarios"]:
        logger.info(
            f"{s['name']}: shock {s['shock']} {s['unit']} "
            f"({s['reference']['start']} ~ {s['reference']['end']})"
        )


if __name__ == "__main__":
    main()
