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
    weight: float = Field(description="섹터 비중(%)")


class MaxAsset(BaseModel):
    ticker: str
    weight: float


class Concentration(BaseModel):
    max_asset: MaxAsset
    max_sector: SectorWeight


class Correlation(BaseModel):
    tickers: list[str]
    matrix: list[list[float]]


class RiskContribution(BaseModel):
    ticker: str
    share: float = Field(description="포트폴리오 변동성 중 이 자산 몫(%), 합계 100")


class FactorBeta(BaseModel):
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
    loss_usd: float


class StressResult(BaseModel):
    scenario: str
    name: str
    shock: float
    unit: str
    loss_pct: float
    loss_usd: float
    by_asset: list[AssetLoss]


class AnalyzeResponse(BaseModel):
    as_of: str
    window: Window
    value_usd: float
    allocation: list[AssetWeight]
    sector: list[SectorWeight]
    concentration: Concentration
    correlation: Correlation
    volatility: float = Field(description="연율 변동성(%)")
    risk_contribution: list[RiskContribution]
    # D6–D7에 채움. 형식만 먼저 고정
    factor_exposure: FactorExposure | None = None
    stress: list[StressResult] | None = None
