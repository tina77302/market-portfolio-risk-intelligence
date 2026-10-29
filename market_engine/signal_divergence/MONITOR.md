# Korea Signal Divergence Monitor MVP

## Scope and status

IMPLEMENTED: read-only Python calculation/export, exact-date integration, diagnostic historical dataset, latest/last-complete outputs, Next.js historical dashboard, observation selector, breadth trend, confirmation layer, research evidence and October case study.

VALIDATED: unit/integration tests cover trading-observation persistence, boundaries, missingness, duplicate dates, 0–1 units, chronological joins, blind-spot exclusion when MSI is stressed, prefix invariance, stored past-only percentile samples and October activation timing. This is implementation validation, **not a reproduction of reported episode statistics**.

EXPERIMENTAL: the selected breadth candidate and current-active-universe retrospective research. Survivorship bias remains. V1 is the frozen reference; V2-A's research selection does not establish a production deployment.

NOT IMPLEMENTED: live ingestion, scheduled refresh, post-OOS frozen-model inference, portfolio modules, point-in-time universe reconstruction, exchange-calendar freshness verification, and production deployment.

## Run locally

From the repository root, using the existing Python environment and installed frontend dependencies:

```bash
.venv/bin/python -m market_engine.signal_divergence.monitor
.venv/bin/python -m unittest discover -s tests -p 'test_signal_divergence_monitor.py' -v
cd frontend
npx tsc --noEmit
npm run lint
npm run build
npm run dev
```

Open http://localhost:3000. For production mode after a successful build, use `npm start` instead of `npm run dev`.

The exporter resolves source paths relative to its module, so it can run from any directory. Optional `--root /path/to/repository` and `--output /path/to/export.json` arguments support alternative local research checkouts. The default JSON destination is `frontend/public/data/korea-monitor.json`; this snapshot can be retained with frontend source so the dashboard works without local research CSVs. The separately generated CSV is `data/processed/signal_divergence/monitor/korea_monitor_history.csv` and inherits the repository's data ignore rules. Existing artifacts are never written. Re-export and restart the development server, or rebuild production, after updating inputs; the dashboard reads its export at build/server rendering, not from a live pipeline. No API/backend service is required. `/data/korea-monitor.json` is the downloadable static research export.

## Data contract and provenance

| Source | Input | Last stored date at implementation |
|---|---|---|
| Frozen V1 OOS | `data/processed/early_warning_v2/korea_oos_predictions_v1_reproduction_10d.csv`, `Prob_XGBoost` | 2026-09-16 |
| Official MSI + threshold | `data/processed/early_warning_v2/korea_feature_matrix_v1_reproduction.csv`, `Korea_MSI`, `Stress_Threshold` | 2026-10-02 |
| Breadth | `data/processed/signal_divergence/korea_breadth_features.csv` | 2026-10-27 |
| Correlation | `data/processed/signal_divergence/cross_asset_signal.csv` | 2026-10-02 |
| Reported holdout V1 + returns | October table in `early_warning_v2/EXPERIMENTS.md` | Reported rounded research values |
| Historical evidence + case interpretation | `VALIDATION.md` | Preserved reported results |

The V1 feature builder imports stored official targets including the date-specific threshold. The monitor uses those values directly; it does not calculate a fixed or new MSI threshold. Existing MSI research describes the official threshold as a past-only expanding 90th percentile. MSI is an index, **not** a bounded probability; no 0–1 constraint is imposed on it. V1 probabilities, stock shares and percentile ranks must use 0–1 units; ambiguous percentage data is rejected, not silently rescaled.

Exports include source row counts, latest dates, SHA-256 fingerprints, schema version, dependency issues, all historical diagnostics, latest observation, last complete monitoring observation, and holdout evidence. Invalid/missing sources are quarantined as unavailable and recorded in `issues`; calculations using their inputs remain unknown. Dates must be unique daily dates. Numeric infinities and out-of-range probabilities are rejected. Nulls stay null in JSON.

## Frozen rule and chronology

The existing breadth builder stores empirical past-only CDF ranks: `(prior valid values <= today's value).mean()`, after 252 prior row positions. The monitor consumes those stored ranks and matches the validated research's **rank >=0.90** convention, including ties. It does not change the rule to a newly fitted strict `value > quantile` test. The six measures are decline breadth, 1D losses ≥2%, 5D losses ≥5%, drawdowns ≥10%, high volatility and abnormal volume.

At least two extreme measures qualify one observation. At least two qualifying observations in a complete three-observation window establish breadth persistence. All six raw measures and percentile ranks must be available; all three qualifying observations must be known. This conservative missingness policy prevents incomplete inputs from being interpreted as stable markets. Windows follow the sorted union of actual V1/MSI/breadth source dates, never calendar-day resampling. If a breadth date is absent while another primary source has that trading date, the missing observation breaks completeness rather than shortening the window. A date absent from every source cannot be identified as a missing trading day without an exchange calendar; no observation is invented.

Calculations occur before limiting dashboard history to the 2016-09-13 OOS start. Joins are exact-date, one-to-one and never backfilled or forward-filled. The correlation research input already contains up to three carried U.S. holiday observations; this inherited limitation is disclosed and correlation is confirmation only. Same-date international market close timing is not resolved.

## State precedence

All primary inputs (V1, MSI, official threshold, complete breadth window) are required. Correlation is optional.

1. Any required input missing → `UNKNOWN / INSUFFICIENT DATA`.
2. V1 ≥0.50 → `ALIGNED RISK` when MSI ≥official threshold **or** breadth persists; otherwise `MODEL-LED WARNING`.
3. V1 <0.50 and MSI ≥official threshold → `OBSERVED MSI STRESS`. This explicit exception is **not** called a V1+MSI blind spot, regardless of breadth.
4. V1 <0.50 and MSI <official threshold → `SIGNAL DIVERGENCE` when breadth persists; otherwise `NORMAL`.

A divergence flag is observed deterioration in disagreement with the predictive model, not a calibrated crash probability or verified future stress event. Future target labels are never used for classification. Correlation confirms only when both stored absolute-correlation ranks are ≥0.90; it never changes the market state.

## October holdout and availability

The stored breadth data reproduces persistence absent on October 12 and active on October 13–15. `VALIDATION.md` reports divergence activation on October 13, **after** the initial October 12 selloff; it was not an advance prediction of that initial decline. The dashboard shows rounded V1 values parsed from the frozen EXPERIMENTS.md table, separately labeled as reported research, never as OOS/live observations. October MSI/threshold and post-OOS V1 prediction records are absent from the integrated CSVs, so the full holdout divergence classification is unavailable to independent recomputation here.

Latest primary observation is October 27 but final state is UNKNOWN because V1 and MSI are unavailable on that date. Last complete observation is September 16. These dates and states remain separate; there is no carried-forward historical state. Age is displayed in calendar days using the observation's Korean midnight, **not** an assertion about the last exchange session.

Historical evidence remains 18 eligible blind stress episodes, 6 detected, 33.3% coverage, median lead 6 trading days and approximately 4.2 false-warning episodes/year. Values are reported unchanged from VALIDATION.md. No model, feature specification, threshold or research validation record has been changed.

## Recommended next milestone

Provide an auditable frozen-V1 inference and official-MSI refresh export with point-in-time timestamps, exchange-calendar freshness and cross-source reconciliation. Validate that extension separately before claiming operational monitoring. Address point-in-time breadth membership before production-grade historical claims.

## Frontend build compatibility

The installed Next.js 16.4.3 guide requires explicit caching for the asynchronous local export read with Cache Components. The page uses `use cache`. This environment returned empty captured output from Next's default TypeScript CLI `--showConfig` invocation; the documented `experimental.useTypeScriptCli: false` compiler API fallback is configured. Type checking remains enabled, and standalone `npx tsc --noEmit` is still required.

## Implementation verification (2026-10-29)

- Python unittest: 10 tests passed.
- `cd frontend && npx tsc --noEmit`: passed.
- `cd frontend && npm run lint`: passed.
- `cd frontend && npm run build`: passed, including type checking and static prerender.
- Production `npm start` smoke check: page and `/data/korea-monitor.json` returned HTTP 200; rendered page contained latest UNKNOWN, last-complete date and the holdout non-prediction statement; export contained 2,479 monitoring rows. Temporary verification server was stopped.
- Input fingerprints matched after verification; existing research scripts, models and validation records were unchanged.
- Browser visual/interactivity QA was not performed; HTTP/SSR smoke verification does not establish visual or browser-interaction correctness.
