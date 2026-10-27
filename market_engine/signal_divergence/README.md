# Signal Divergence Monitor

## Objective

Detect potential market-risk blind spots when the Early Warning model remains below its warning threshold while independent market signals are deteriorating.

Signal Divergence is NOT:
- a second crash prediction model
- a lower Risk Score threshold
- a replacement for MSI
- a rule designed specifically to catch the October 2026 event

## Core Structure

Predictive Risk
- Early Warning V1 / V2 Risk Score
- Forward-looking ML estimate

Independent Market Monitor
- Market Breadth / Stress Diffusion
- FX Stress
- Volatility Structure
- Cross-Asset Correlation
- Liquidity proxy, if reliable data is available

## Divergence State

1. Low model risk + stable market signals
   -> Normal

2. High model risk + deteriorating market signals
   -> Aligned Risk

3. High model risk + stable market signals
   -> Model-Led Warning

4. Low model risk + deteriorating market signals
   -> Signal Divergence / Potential Blind Spot

## Research Rules

- Risk Score threshold remains frozen at 0.50 for V1 comparison.
- October 2026 must not be used to tune thresholds.
- Independent signals must use past/current information only.
- Signals already used heavily by the prediction model must not simply be repackaged as independent evidence.
- Candidate signals must be evaluated over historical OOS periods.
- A signal that fails historical validation will be rejected even if it explains October 2026 retrospectively.

## Validation

Evaluate:

- Stress-event coverage
- False-signal rate
- Lead time
- Coverage of Early Warning false negatives
- Incremental value over Risk Score alone
- Incremental value over Risk Score + MSI
- Stability across market regimes

## Prior Research

Project V1 previously tested:

- RSP/SPY breadth features as ML inputs
- 43-industry stress transmission research
- October 2026 retrospective stress analysis

These studies are research references only and are not treated as production-valid Signal Divergence evidence.

Known limitations of the prior industry-transmission study include:

- survivorship bias
- classification look-ahead
- retrospective current-universe construction
- non-production eligibility

The new Signal Divergence Monitor must address these limitations or explicitly preserve them as research limitations.
