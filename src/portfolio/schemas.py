from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from src.portfolio.universe import load_universe

MAX_HOLDINGS = 10
# 비중 합계 허용오차(%p)
WEIGHT_TOLERANCE = 0.01

SUPPORTED_TICKERS = frozenset(load_universe().index)


# ---------- 요청 ----------

class Holding(BaseModel):
    ticker: str
    weight: float = Field(gt=0, le=100, description="투자 비중(%)")

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, v):
        return v.strip().upper()


class AnalyzeRequest(BaseModel):
    holdings: list[Holding] = Field(min_length=1, max_length=MAX_HOLDINGS)
    value_usd: float = Field(
        gt=0, allow_inf_nan=False, description="포트폴리오 평가금액(USD)"
    )

    @model_validator(mode="after")
    def check_portfolio(self):
        tickers = [h.ticker for h in self.holdings]

        duplicated = sorted({t for t in tickers if tickers.count(t) > 1})
        if duplicated:
            raise ValueError(f"중복된 티커가 있습니다: {duplicated}")

        unknown = sorted(set(tickers) - SUPPORTED_TICKERS)
        if unknown:
            raise ValueError(f"지원하지 않는 티커입니다: {unknown}")

        total = sum(h.weight for h in self.holdings)
        if abs(total - 100) > WEIGHT_TOLERANCE:
            raise ValueError(f"비중 합계가 100%가 아닙니다: {total:.2f}%")

        return self


class CompareRequest(BaseModel):
    """What-if 요청. 비중만 바꾸고 같은 평가금액으로 비교합니다."""

    current: AnalyzeRequest
    proposed: AnalyzeRequest

    @model_validator(mode="after")
    def check_same_value(self):
        if self.current.value_usd != self.proposed.value_usd:
            raise ValueError("변경 전후 평가금액(value_usd)이 같아야 합니다.")
        return self


# ---------- 응답 ----------

class Window(BaseModel):
    start: str
    end: str
    days: int


class AssetWeight(BaseModel):
    ticker: str
    name: str
    sector: str
    weight: float = Field(description="투자 비중(%)")


class SectorWeight(BaseModel):
    sector: str
    weight: float = Field(description="자산 분류 기준 비중(%). ETF 내부 보유종목 미반영")


class SectorMethodology(BaseModel):
    classification: Literal["asset_level"]
    etf_lookthrough: Literal[False]
    label: str = Field(description="비중·집중도 화면에 표시할 집계 기준")
    limitations: list[str] = Field(min_length=1)


class MaxAsset(BaseModel):
    ticker: str
    weight: float


class Concentration(BaseModel):
    max_asset: MaxAsset
    max_sector: SectorWeight = Field(description="자산 분류 기준 최대 비중. ETF 내부 보유종목 미반영")


class Correlation(BaseModel):
    tickers: list[str]
    matrix: list[list[float]]


class RiskContribution(BaseModel):
    ticker: str
    share: float = Field(description="포트폴리오 변동성 중 이 자산 몫(%), 합계 100")


class FactorBeta(BaseModel):
    """각 팩터를 따로 회귀한 민감도. 다른 팩터의 영향을 통제하지 않습니다."""

    market: float = Field(description="SPY 수익률 1당 수익률(소수)")
    rate: float = Field(description="10년 금리 1bp당 수익률(소수)")
    volatility: float = Field(description="VIX 1pt당 수익률(소수)")


class AssetFactorExposure(FactorBeta):
    ticker: str


class FactorExposure(FactorBeta):
    by_asset: list[AssetFactorExposure] = Field(
        min_length=1,
        max_length=MAX_HOLDINGS,
        description="보유 자산별 베타. allocation과 같은 순서로 티커마다 한 번씩 반환",
    )


class AssetLoss(BaseModel):
    ticker: str
    loss_usd: float = Field(
        description="비중을 반영한 자산별 손실 기여액(USD). 양수=손실, 음수=이익"
    )


class StressResult(BaseModel):
    """팩터 하나에 대한 선형 근사. 시나리오 간 손실은 합산하지 않습니다."""

    scenario: str
    name: str
    factor: Literal["market", "rate", "volatility"]
    shock: float
    unit: str
    loss_pct: float = Field(description="손실률(%). 양수=손실, 음수=이익")
    loss_usd: float = Field(
        description="자산별 손실 기여액의 합계(USD). 양수=손실, 음수=이익"
    )
    by_asset: list[AssetLoss] = Field(
        description="이익이 난 자산도 포함하며 allocation과 같은 순서로 반환"
    )


class AnalysisMethodology(BaseModel):
    regression: Literal["separate_univariate"]
    beta_frequency: Literal["daily"]
    shock_horizon_days: int = Field(gt=0, description="충격 산출 기간(거래일)")
    approximation: Literal["linear_beta_times_shock"]
    scenarios_additive: Literal[False] = Field(
        description="팩터 간 영향이 중복될 수 있으므로 시나리오별 손실 합산 불가"
    )
    is_forecast: Literal[False] = Field(description="선형 민감도 근사이며 미래 손실 예측이 아님")
    limitations: list[str] = Field(min_length=1, description="결과 해석 시 표시할 한계")


class AnalyzeResponse(BaseModel):
    as_of: str
    window: Window
    value_usd: float
    allocation: list[AssetWeight]
    sector: list[SectorWeight]
    sector_methodology: SectorMethodology
    concentration: Concentration
    correlation: Correlation
    volatility: float = Field(description="연율 변동성(%)")
    risk_contribution: list[RiskContribution]
    methodology: AnalysisMethodology
    # 스냅샷 추정 기간(window)의 베타로 계산
    factor_exposure: FactorExposure | None = None
    stress: list[StressResult] | None = Field(
        default=None,
        description="시나리오별 선형 근사. 개별 비교용이며 손실을 합산하지 않음",
    )


class ComparisonRow(BaseModel):
    metric: str
    label: str
    unit: Literal["%", "usd", "beta"]
    current: float
    proposed: float
    change: float = Field(description="proposed - current. 손실 지표에서 양수 = 손실 증가")
    current_detail: str | None = Field(default=None, description="해당 값의 자산·섹터 이름")
    proposed_detail: str | None = None


class CompareResponse(BaseModel):
    current: AnalyzeResponse
    proposed: AnalyzeResponse
    comparison: list[ComparisonRow]
