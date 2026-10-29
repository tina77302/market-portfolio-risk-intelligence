# Market & Portfolio Risk Intelligence

An integrated risk intelligence platform for market stress prediction, signal divergence detection, portfolio hidden risk analysis, stress simulation, and risk-aware optimization.

## Core Modules
- Early Warning V2
- Signal Divergence Monitor
- Portfolio Hidden Risk Map
- Risk Regime Digital Twin
- Adaptive Stress Lab
- Risk-Aware Portfolio Optimization

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
