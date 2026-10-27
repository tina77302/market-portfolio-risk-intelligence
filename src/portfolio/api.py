import json

from fastapi import APIRouter

from src.portfolio.analytics import (
    analyze_portfolio,
    load_snapshot_meta,
    load_window_returns,
)
from src.portfolio.scenarios import SCENARIOS_PATH
from src.portfolio.schemas import AnalyzeRequest, AnalyzeResponse
from src.portfolio.universe import load_universe

# 메인 앱에서 app.include_router(router) 한 줄로 연결합니다.
router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("/universe")
def get_universe():
    """지원 자산 목록"""
    assets = load_universe().reset_index()
    return {"assets": assets.to_dict(orient="records")}


@router.get("/scenarios")
def get_scenarios():
    """Stress 시나리오 정의·충격 크기·근거 구간"""
    return json.loads(SCENARIOS_PATH.read_text())


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze(request: AnalyzeRequest):
    """포트폴리오 Hidden Risk 분석. What-if는 변경 전후로 두 번 호출합니다."""
    weights = {h.ticker: h.weight / 100 for h in request.holdings}
    result = analyze_portfolio(weights, load_window_returns(), load_universe())

    meta = load_snapshot_meta()
    return {
        "as_of": meta["as_of"],
        "window": {
            "start": meta["window_start"],
            "end": meta["window_end"],
            "days": meta["window_days"],
        },
        "value_usd": request.value_usd,
        **result,
    }
