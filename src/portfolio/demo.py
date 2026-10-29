import argparse
import json
from pathlib import Path

from src.portfolio.api import analyze
from src.portfolio.schemas import AnalyzeRequest, AnalyzeResponse

DEMO_DIR = Path(__file__).resolve().parents[2] / "examples" / "portfolio"
EXPECTED_PATH = DEMO_DIR / "expected.json"


def run_demo():
    """고정 요청을 실제 분석 경로로 실행합니다. 데이터 다운로드는 하지 않습니다."""
    summary = {}
    for name in ("before", "after"):
        request = AnalyzeRequest.model_validate_json(
            (DEMO_DIR / f"{name}.json").read_text()
        )
        response = AnalyzeResponse.model_validate(analyze(request))
        window = response.window.model_dump()
        if name == "before":
            summary.update(as_of=response.as_of, window=window)
        elif summary["as_of"] != response.as_of or summary["window"] != window:
            raise ValueError("변경 전후 분석의 스냅샷과 추정 기간이 다릅니다.")
        nvda = next(a for a in response.allocation if a.ticker == "NVDA")
        nvda_risk = next(a for a in response.risk_contribution if a.ticker == "NVDA")
        summary[name] = {
            "volatility": response.volatility,
            "nvda_weight": nvda.weight,
            "nvda_risk_share": nvda_risk.share,
        }
    return summary


def main():
    parser = argparse.ArgumentParser(description="고정 포트폴리오 시연 결과 재현")
    parser.add_argument("--check", action="store_true", help="저장된 기준 결과와 일치하는지 검증")
    args = parser.parse_args()
    result = run_demo()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if args.check and result != json.loads(EXPECTED_PATH.read_text()):
        parser.exit(1, "시연 결과가 expected.json과 다릅니다. 입력·스냅샷·계산 변경을 확인하세요.\n")


if __name__ == "__main__":
    main()
