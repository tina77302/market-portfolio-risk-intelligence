# Market & Portfolio Risk Intelligence

A risk intelligence workflow that validates a market stress early-warning model and connects market risk to portfolio hidden risk, stress testing, and what-if comparison.

**Predict → Diagnose → Stress → Compare**

## Core Modules
- **Early Warning V2 & Market Monitor**: reproduce the Korea V1 model, test downside/tail risk features under the same purged walk-forward OOS setup, and adopt V2 only if it improves out of sample
- **Portfolio Hidden Risk Map**: asset concentration, asset-level sector/class weights without ETF look-through, correlation, volatility, risk contribution, and factor sensitivity for up to 10 U.S. stocks and ETFs
- **Portfolio Stress Test**: estimated P&L under three fixed shocks (equity sell-off, interest rate shock, volatility shock)
- **What-if Analysis**: change weights and compare before and after with the same risk engine

The market Risk Score is a market-level signal, not a loss probability for a specific portfolio.

## Out of Scope
Kept as future research: Signal Divergence Alert Engine, Risk Regime Digital Twin, Adaptive Stress Lab, Risk-Aware Portfolio Optimization.

## Portfolio Module

```bash
python -m src.portfolio.data        # fetch prices, VIX, DGS10 into data/raw/ (gitignored)
python -m src.portfolio.snapshot    # freeze data/portfolio/prices.csv, factors.csv as of the latest complete date
python -m src.portfolio.scenarios   # size stress shocks into data/portfolio/scenarios.json
python -m pytest tests
```

API router (`src/portfolio/api.py`), mounted with `app.include_router(router)`:

| Endpoint | Description |
| --- | --- |
| `GET /api/portfolio/universe` | Supported assets with sector and asset class |
| `GET /api/portfolio/scenarios` | Scenario definitions, shock sizes, historical reference windows |
| `POST /api/portfolio/analyze` | `{"holdings": [{"ticker", "weight"}], "value_usd"}` → hidden risk analysis (weights in %) |

`/universe` and `/analyze` include `sector_methodology` with
`classification: "asset_level"`, `etf_lookthrough: false`, a display `label`, and
`limitations`. Display the label **자산 분류 기준 비중 (ETF 내부 보유종목 미반영)**
beside `sector` and `concentration.max_sector`.

ETFs count as one asset using the category in `universe.csv`; their holdings are
not expanded. AAPL 50% plus QQQ 50%, for example, is reported as Information
Technology 50% and Broad Equity 50%. This does not measure the actual underlying
technology exposure or account for overlapping holdings. Treasury, Credit, and
Commodity are asset categories rather than equity sectors.

`factor_exposure` is `null` until the D6–D7 factor calculations are connected.
Once available, it contains the portfolio betas and a required `by_asset` list:

| Response field | Meaning |
| --- | --- |
| `factor_exposure.market` | Portfolio return per unit of SPY return |
| `factor_exposure.rate` | Portfolio return per 1 bp change in DGS10 |
| `factor_exposure.volatility` | Portfolio return per 1 point change in VIX |
| `factor_exposure.by_asset[].ticker` | Holding ticker, once per holding in `allocation` order |
| `factor_exposure.by_asset[].market` | Asset return per unit of SPY return |
| `factor_exposure.by_asset[].rate` | Asset return per 1 bp change in DGS10 |
| `factor_exposure.by_asset[].volatility` | Asset return per 1 point change in VIX |

Beta return units are decimal, not percentages. The asset betas describe each
asset before portfolio weighting; portfolio betas are their weight-adjusted sums.
Missing estimates must not be represented as zero betas.

`stress` is `null` until factor betas are available. Each scenario uses the same
loss convention: **positive = loss, negative = gain, zero = no change**.
An asset's estimated return is its factor beta multiplied by that scenario's
shock, using the beta and shock units above.

| Response field | Formula / units |
| --- | --- |
| `stress[].loss_pct` | `-100 * sum(weight * asset_return)`; percent, rounded to 4 decimals |
| `stress[].by_asset[].loss_usd` | `-value_usd * weight * asset_return`; USD, rounded to cents |
| `stress[].loss_usd` | Sum of the rounded asset loss amounts, including gains |

Weights in these formulas are decimal fractions. Currency rounding uses half up;
the total is calculated from the asset amounts so the displayed amounts reconcile.
The percentage uses unrounded returns, so a small currency rounding difference
can exist between the reported total and `value_usd * loss_pct / 100`.
All holdings appear in `by_asset`, in `allocation` order. Negative contributions
must be preserved when an asset offsets other losses.

For example, a beta of 1 under a -20% market shock produces `loss_pct: 20` and
`loss_usd: 20000` for a USD 100,000 position. A beta of -1 under the same shock
produces `loss_pct: -20` and `loss_usd: -20000` (a gain).

Both `/api/portfolio/analyze` and `/api/portfolio/scenarios` return `methodology`
with `regression: "separate_univariate"`, `beta_frequency: "daily"`,
`shock_horizon_days: 10`, `approximation: "linear_beta_times_shock"`,
`scenarios_additive: false`, `is_forecast: false`, and explanatory `limitations`.
These fields define the D6 calculation contract even while betas and stress
results are `null`.

Fit each beta separately using daily asset returns and one daily factor
(SPY return, DGS10 change in bp, or VIX change in points). These are marginal
sensitivities; they do not isolate the factor's effect after controlling for the
other factors and do not establish causation.

Each stress row identifies its `factor` and applies only that factor's beta to
its shock. **Compare the scenarios separately; never sum their losses.**
Correlated factors may reflect the same market movement, so adding the results
can double-count exposure. The separate regressions do not imply statistical
independence or define a joint multi-factor shock.

Applying a daily beta to a historical 10-trading-day shock is a linear sensitivity
approximation. It is not a fitted 10-day return model, a future loss forecast,
or an event probability. Extreme shocks can fall outside the daily regression's
usual range. Clients should display the interpretation in `methodology.limitations`
alongside factor and stress results and provide no combined-scenario loss total.

## Reproducible portfolio demo

The exact `/api/portfolio/analyze` requests are saved in
[`examples/portfolio/before.json`](examples/portfolio/before.json) and
[`examples/portfolio/after.json`](examples/portfolio/after.json). The starting
USD 100,000 portfolio holds AAPL/MSFT at 30% each and NVDA/AMZN at 20% each.
The comparison keeps 70% of every original holding and allocates 10% each to
TLT, GLD, and XLV. Both portfolios remain fully invested at the same value.

Using the frozen 2026-10-23 snapshot and 756 daily returns (2023-10-19 through
2026-10-23), the recorded results are:

| Metric | Before | After |
| --- | --- | --- |
| Annualized volatility | 23.38% | 17.22% |
| NVDA investment weight | 20.00% | 14.00% |
| NVDA risk contribution share | 30.43% | 28.22% |

Run the real analysis code against the fixed requests without downloading data:

```bash
python -m src.portfolio.demo --check
```

The command prints the recalculated summary and exits with a nonzero status if
it differs from [`expected.json`](examples/portfolio/expected.json). Snapshot or
input updates therefore require reviewing and updating the recorded demo results.
