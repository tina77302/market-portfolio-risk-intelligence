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

## Korea Market Monitor MVP

A local historical dashboard now integrates the frozen **V1** OOS reference,
existing breadth research and stored official MSI thresholds. No live feed or
portfolio functionality is implied. See [monitor implementation and data contract](market_engine/signal_divergence/MONITOR.md)
for source provenance, state precedence, limitations and validation.

```bash
.venv/bin/python -m market_engine.signal_divergence.monitor
cd frontend
npm run dev
```

Open http://localhost:3000. The retained JSON export is a historical research
snapshot; re-export and rebuild/restart after source updates.

## Global research dashboard

The frontend now provides a Korean-first KR/EN application with dedicated US,
Korea, breadth, validation, case-study, source and methodology pages. Verified
historical US V1 files are copied into a separate presentation snapshot; the
original completed project remains distinct from this project's experimental
Korea module. Current missing observations remain unavailable.

See [frontend usage](frontend/README.md) and
[redesign, source coverage and verification](frontend/docs/REDESIGN.md).

## Portfolio Module

To run the full demo (API + dashboard) and present it step by step, see
[docs/PORTFOLIO_DEMO.md](docs/PORTFOLIO_DEMO.md).

```bash
python -m src.portfolio.data        # fetch prices, VIX, DGS10 into data/raw/ (gitignored)
python -m src.portfolio.snapshot    # freeze data/portfolio/prices.csv, factors.csv as of the latest complete date
python -m src.portfolio.scenarios   # size stress shocks into data/portfolio/scenarios.json
python -m pytest tests
```

Run the portfolio API on its own (CORS allows `http://localhost:3000` by default;
override with comma-separated `PORTFOLIO_API_CORS_ORIGINS`):

```bash
uvicorn src.portfolio.server:app --port 8000   # GET /health returns the snapshot date
```

A main app can instead mount the router (`src/portfolio/api.py`) with `app.include_router(router)`:

| Endpoint | Description |
| --- | --- |
| `GET /api/portfolio/universe` | Supported assets with sector and asset class |
| `GET /api/portfolio/scenarios` | Scenario definitions, shock sizes, historical reference windows |
| `POST /api/portfolio/analyze` | `{"holdings": [{"ticker", "weight"}], "value_usd"}` → hidden risk analysis (weights in %) |
| `POST /api/portfolio/compare` | `{"current": <analyze request>, "proposed": <analyze request>}` → both analyses plus a before/after `comparison` table |

`/compare` is the What-if endpoint. Both portfolios must use the same `value_usd`,
and each is validated like an `/analyze` request. `comparison` rows cover the
maximum asset and sector weights (with the asset or sector name in
`current_detail` / `proposed_detail`), volatility, market beta, and each
scenario's `loss_pct` and `loss_usd`. `change` is `proposed - current`, so a
positive change in a loss row means a larger loss.

`/universe` and `/analyze` include `sector_methodology` with
`classification: "asset_level"`, `etf_lookthrough: false`, a display `label`, and
`limitations`. Display the label **자산 분류 기준 비중 (ETF 내부 보유종목 미반영)**
beside `sector` and `concentration.max_sector`.

ETFs count as one asset using the category in `universe.csv`; their holdings are
not expanded. AAPL 50% plus QQQ 50%, for example, is reported as Information
Technology 50% and Broad Equity 50%. This does not measure the actual underlying
technology exposure or account for overlapping holdings. Treasury, Credit, and
Commodity are asset categories rather than equity sectors.

`factor_exposure` is estimated from the snapshot over the same `window` as
volatility and correlation (756 trading days). It contains the portfolio betas
and a required `by_asset` list:

| Response field | Meaning |
| --- | --- |
| `factor_exposure.market` | Portfolio return per unit of SPY return |
| `factor_exposure.rate` | Portfolio return per 1 bp change in DGS10 |
| `factor_exposure.volatility` | Portfolio return per 1 point change in VIX |
| `factor_exposure.by_asset[].ticker` | Holding ticker, once per holding in `allocation` order |
| `factor_exposure.by_asset[].market` | Asset return per unit of SPY return |
| `factor_exposure.by_asset[].rate` | Asset return per 1 bp change in DGS10 |
| `factor_exposure.by_asset[].volatility` | Asset return per 1 point change in VIX |
| `factor_exposure.by_asset[].t_stat` / `.significant` | t value per factor and whether `|t| >= methodology.significance_t` (2) |
| `factor_exposure.t_stat` / `.significant` | Same for the portfolio, from regressing daily portfolio returns on each factor |

A `t_stat` of `null` means a perfect fit (SPY on the market factor), which counts
as significant. A beta that is not significant is not distinguishable from zero,
so its sign should not be presented as a finding.

Beta return units are decimal, not percentages. The asset betas describe each
asset before portfolio weighting; portfolio betas are their weight-adjusted sums.
Missing estimates must not be represented as zero betas.

`stress` is computed from those betas. Each scenario uses the same
loss convention: **positive = loss, negative = gain, zero = no change**.
An asset's estimated return is its factor beta multiplied by that scenario's
shock, using the beta and shock units above.

| Response field | Formula / units |
| --- | --- |
| `stress[].loss_pct` | `-100 * sum(weight * asset_return)`; percent, rounded to 4 decimals |
| `stress[].by_asset[].loss_usd` | `-value_usd * weight * asset_return`; USD, rounded to cents |
| `stress[].loss_usd` | Sum of the rounded asset loss amounts, including gains |
| `stress[].significant` | Whether the portfolio beta for this scenario's factor is significant; `false` means the loss or gain cannot be told apart from zero |

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
with `regression: "separate_univariate"`, `beta_frequency: "daily"`, `significance_t: 2`,
`shock_horizon_days: 10`, `approximation: "linear_beta_times_shock"`,
`scenarios_additive: false`, `is_forecast: false`, and explanatory `limitations`.
These fields describe how `factor_exposure` and `stress` are calculated.

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
The comparison keeps 70% of every original holding and moves the freed 30% into
long Treasuries (TLT). Both portfolios remain fully invested at the same value.

Using the frozen 2026-10-23 snapshot and 756 daily returns (2023-10-19 through
2026-10-23), the recorded results are:

| Metric | Before | After |
| --- | --- | --- |
| Annualized volatility | 23.38% | 16.94% |
| NVDA investment weight | 20.00% | 14.00% |
| NVDA risk contribution share | 30.43% | 28.37% |
| Equity sell-off loss | 30.16% | 21.95% |
| Interest rate shock loss | −0.84% (not significant, t 1.21) | 2.33% (significant, t −4.66) |

The shift lowers the equity and volatility shock losses and adds a rate-shock
loss that was not distinguishable from zero before.

### Stress 검증: historical loss replay

The [Stress 검증](reports/portfolio/stress_validation_report.md) compares estimates with
realized buy-and-hold losses for all 28 supported assets and the two demo
portfolios. Betas use only observations strictly before each interval starts.
Three frozen stress cases are complemented by 145 non-overlapping 10-day
intervals with full 756-return training windows. The 2020 cases have shorter
available histories and are flagged separately.

```bash
python -m analysis.portfolio_stress_validation
python -m pytest tests/test_portfolio_stress_validation.py
```

These are conditional replays using realized factor shocks, not forecasts of
shocks or total losses. Single-factor estimates can materially overstate or
understate realized losses; see the report for baselines, errors and limitations.

### Stress 검증: joint-factor replay experiment

The [joint-factor experiment](reports/portfolio/joint_stress/experiment.md)
fits equity/rate and equity/rate/VIX coefficients together, then applies each
interval's jointly observed shocks. It keeps the same pre-start training cutoff,
daily beta approximation and 145 evaluation intervals, and includes a matched
training-sample control for missing rate observations.

```bash
python -m analysis.portfolio_joint_stress_experiment
python -m pytest tests/test_portfolio_joint_stress_experiment.py
```

The joint models improve average errors in this retrospective comparison, but
some fixed crisis cases deteriorate. Production single-factor scenarios and
the original Stress 검증 artifacts remain separate; fresh holdout validation is required
before operational adoption.

### Second Stress 검증 revision: direct 10-day returns

The [direct 10-day experiment](reports/portfolio/direct_10d_stress/stress_validation_report.md)
fits equity/rate coefficients to non-overlapping 10-trading-day asset returns.
Every training block ends strictly before its evaluation interval starts.
It compares models with and without the fitted intercept and preserves the
first revision as the daily-beta baseline on the same 145 evaluation intervals.

```bash
python -m analysis.portfolio_horizon_stress_experiment
python -m pytest tests/test_portfolio_horizon_stress_experiment.py
```

The direct-return candidates improve the fixed crisis cases but worsen average
and tail-underestimation errors relative to the first revision. They are not
selected to replace that candidate. Training-block dates, counts and missing
endpoint exclusions are retained for inspection.

### Stress 검증: situation-specific error diagnostics

The [situation diagnostics](reports/portfolio/regime_stress/stress_validation_report.md)
partition the first revision's fixed 145 intervals by realized equity/rate
shocks. They report error direction, actual-loss-only underestimation, additive
error contributions, chronological halves and a fixed nine-definition threshold
sensitivity check. No model is refitted or selected by regime.

```bash
python -m analysis.portfolio_regime_stress_diagnostics
python -m pytest tests/test_portfolio_regime_stress_diagnostics.py
```

The primary equity-down and joint-shock buckets have only three and two
intervals. Some bias directions change across periods or thresholds, so these
diagnostics do not establish a stable correction or a prospective regime rule.

### Stress 검증: historical-error bands and empirical coverage

The [error-band validation](reports/portfolio/error_band_stress/stress_validation_report.md)
adds bounds around the first revision's unchanged point estimates. Calibration
uses up to 60 errors whose outcome end is strictly before each evaluation start,
with a minimum of 30. The first 31 intervals remain unavailable; 114 are scored.
Signed-error bounds and a symmetric absolute-error comparator use identical
eligible dates. Coverage, width, upper-loss exceedances and interval scores are
reported overall, by chronological half, and by realized market situation.

```bash
python -m analysis.portfolio_error_band_validation
python -m pytest tests/test_portfolio_error_band_validation.py
```

The 90% target is a design setting, not a guaranteed future probability. Overall
historical coverage exceeds 90%, while loss-only coverage is lower and the bands
remain wide. No production forecast or loss limit is implied.

### Stress 검증: paper-forward collection pipeline

The [new-period pipeline](docs/PORTFOLIO_FORWARD_VALIDATION_KO.md) seals the
rules/runtime, then freezes each interval's betas and historical-error offsets
before its start. It evaluates only after ten further observed SPY sessions,
appends immutable receipts/results, and exports cumulative conditional-error
and coverage metrics. Historical warm-start errors are excluded from forward
performance counts. Stale inputs and collection failures remain waiting states.

```bash
python -m src.portfolio.forward_validation run --refresh
python -m src.portfolio.forward_validation status
python -m pytest tests/test_portfolio_forward_validation.py
```

The GitHub Actions workflow includes weekday collection and state restoration;
it runs only after the workflow is present on the remote default branch and
Actions is enabled. See the [actual readiness check](reports/portfolio/forward_stress/stress_validation_report.md).

Run the real analysis code against the fixed requests without downloading data:

```bash
python -m src.portfolio.demo --check
```

The command prints the recalculated summary and exits with a nonzero status if
it differs from [`expected.json`](examples/portfolio/expected.json). Snapshot or
input updates therefore require reviewing and updating the recorded demo results.
