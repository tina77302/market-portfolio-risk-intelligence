# Market & Portfolio Risk Intelligence

A risk intelligence workflow that validates a market stress early-warning model and connects market risk to portfolio hidden risk, stress testing, and what-if comparison.

**Predict → Diagnose → Stress → Compare**

## Core Modules
- **Early Warning V2 & Market Monitor**: reproduce the Korea V1 model, test downside/tail risk features under the same purged walk-forward OOS setup, and adopt V2 only if it improves out of sample
- **Portfolio Hidden Risk Map**: asset and sector concentration, correlation, volatility, risk contribution, and factor sensitivity for up to 10 U.S. stocks and ETFs
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
