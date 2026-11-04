"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useDashboard } from "@/components/dashboard-shell";
import { CountryCards } from "@/components/research-panels";
import { PORTFOLIO_API, PortfolioApiError, analyzePortfolio, comparePortfolios, exampleAfter, exampleBefore, getScenarios, getUniverse, inputProblem, type Analysis, type Comparison, type Holding, type Scenarios, type Universe } from "@/lib/portfolio-api";
import { HiddenRiskMap, HoldingsEditor, StressTest, WhatIfTable, usePortfolioCopy } from "./portfolio-panels";
import styles from "./portfolio.module.css";

const DEFAULT_VALUE = 100_000;
type Task = "analyze" | "compare";
const toApiError = (e: unknown) => (e instanceof PortfolioApiError ? e : new PortfolioApiError("network", PORTFOLIO_API));

function ApiProblem({ error }: { error: PortfolioApiError }) {
 const p = usePortfolioCopy();
 if (error.kind === "rejected") return <p className={styles.problem} role="alert">{p("apiRejected")} {error.message}</p>;
 return <section className={`panel ${styles.alert} ${styles.section}`} role="alert"><h2>{p("apiDown")} {error.message}</h2><p>{p("apiStart")}<br/><code>uvicorn src.portfolio.server:app --port 8000</code></p></section>;
}

export default function PortfolioView() {
 const p = usePortfolioCopy();
 const { global, operational } = useDashboard();
 const [universe, setUniverse] = useState<Universe | null>(null);
 const [scenarios, setScenarios] = useState<Scenarios | null>(null);
 const [holdings, setHoldings] = useState<Holding[]>(exampleBefore);
 const [proposed, setProposed] = useState<Holding[]>(exampleAfter);
 const [value, setValue] = useState(DEFAULT_VALUE);
 const [analysis, setAnalysis] = useState<Analysis | null>(null);
 const [comparison, setComparison] = useState<Comparison | null>(null);
 const [busy, setBusy] = useState<Task | null>("analyze");
 const [error, setError] = useState<{ task: Task; error: PortfolioApiError } | null>(null);

 // Load the asset list, scenarios and the example portfolio once the page is in the browser.
 useEffect(() => {
  let active = true;
  Promise.all([getUniverse(), getScenarios(), analyzePortfolio(exampleBefore, DEFAULT_VALUE)])
   .then(([u, s, a]) => { if (active) { setUniverse(u); setScenarios(s); setAnalysis(a); } })
   .catch(e => { if (active) setError({ task: "analyze", error: toApiError(e) }); })
   .finally(() => { if (active) setBusy(null); });
  return () => { active = false; };
 }, []);

 const run = async (task: Task) => {
  setBusy(task);
  setError(null);
  try {
   if (task === "analyze") { setAnalysis(await analyzePortfolio(holdings, value)); setComparison(null); }
   else setComparison(await comparePortfolios(holdings, proposed, value));
  } catch (e) {
   setError({ task, error: toApiError(e) });
  } finally {
   setBusy(null);
  }
 };

 const assets = universe?.assets ?? [];
 const network = error?.error.kind === "network" ? error.error : null;
 // Same date the U.S. card shows: the operational source date when present, else the research snapshot.
 const marketAsOf = operational?.markets.us.expectedDate ?? global?.asOf ?? null;
 const portfolioAsOf = analysis?.as_of ?? scenarios?.as_of ?? null;
 return <main className="dashboard-content view-portfolio">
  <div className="page-hero compact-hero"><div className="hero-copy"><p className="eyebrow">{p("eyebrow")}</p><h1>{p("title")}</h1><p className="hero-subtitle">{p("subtitle")}</p></div>
   <div className="hero-status"><span>{p("dataAsOf")} <b>{analysis?.as_of ?? scenarios?.as_of ?? "N/A"}</b></span><span>{p("window")} <b>{analysis ? `${analysis.window.start} ~ ${analysis.window.end}` : "N/A"}</b></span></div>
  </div>
  <div className={styles.sectionTitle}><span className={styles.step}>STEP 1</span><h2>{p("marketTitle")}</h2><p>{p("marketNote")}</p></div>
  <CountryCards only="us"/>
  <div className="research-banner"><p>{p("riskScoreNote")}{marketAsOf && portfolioAsOf && marketAsOf !== portfolioAsOf && <> {p("dateGap").replace("{market}", marketAsOf).replace("{portfolio}", portfolioAsOf)}</>}</p><Link href="/">{p("checkMarket")} →</Link></div>
  {network && <ApiProblem error={network}/>}

  <section className={`panel ${styles.section}`}>
   <div className="panel-header"><div className={styles.panelTitle}><span className={styles.step}>STEP 2</span><h2>{p("inputTitle")}</h2></div><span className="tag">{p("inputNote")}</span></div>
   <HoldingsEditor label={p("current")} holdings={holdings} onChange={setHoldings} assets={assets} value={value}/>
   <div className={styles.editorFooter}>
    <label className={styles.valueField}>{p("valueLabel")}<input type="number" inputMode="decimal" min="0" step="1000" value={Number.isFinite(value) ? value : ""} onChange={e => setValue(e.target.value === "" ? NaN : Number(e.target.value))}/></label>
    <div className={styles.actions}>
     <button type="button" onClick={() => setHoldings(exampleBefore)}>{p("example")}</button>
     <button type="button" className={styles.primary} disabled={busy !== null || inputProblem(holdings, value) !== null || !universe} onClick={() => run("analyze")}>{busy === "analyze" ? p("analyzing") : p("analyze")}</button>
    </div>
   </div>
   {inputProblem(holdings, value) === "value" && <p className={styles.problem}>{p("value")}</p>}
   {error?.task === "analyze" && error.error.kind === "rejected" && <ApiProblem error={error.error}/>}
  </section>

  {analysis && <><HiddenRiskMap analysis={analysis}/><StressTest analysis={analysis} scenarios={scenarios}/></>}

  <div className={styles.sectionTitle}><span className={styles.step}>STEP 5–6</span><h2>{p("whatifTitle")}</h2><p>{p("whatifIntro")}</p></div>
  <div className={styles.whatifGrid}>
   <section className="panel">
    <div className={styles.actions}><button type="button" onClick={() => setProposed(holdings)}>{p("fromCurrent")}</button><button type="button" onClick={() => setProposed(exampleAfter)}>{p("exampleShift")}</button></div>
    <div className={styles.section}><HoldingsEditor label={p("proposed")} holdings={proposed} onChange={setProposed} assets={assets} value={value}/></div>
    <div className={styles.editorFooter}><span/><button type="button" className={styles.primary} disabled={busy !== null || inputProblem(holdings, value) !== null || inputProblem(proposed, value) !== null || !universe} onClick={() => run("compare")}>{busy === "compare" ? p("comparing") : p("compare")}</button></div>
    {error?.task === "compare" && error.error.kind === "rejected" && <ApiProblem error={error.error}/>}
   </section>
   <section className="panel">{comparison ? <WhatIfTable comparison={comparison}/> : <p>{p("whatifIntro")}</p>}</section>
  </div>
 </main>;
}
