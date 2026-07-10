# Quality-compounder metrics: research findings & panel roadmap

July 2026. Deep research (multi-source, adversarially verified against primary sources) on the
best metrics for return on capital, cash generation, and balance-sheet strength, plus a review of
the current fundamentals panel and which new metrics our FMP quarterly data supports.

Primary sources verified verbatim: Novy-Marx (JFE 2013; "Quality Investing"; "The Quality
Dimension of Value Investing"), Asness/Frazzini/Pedersen QMJ (RAS 2019), NBIM Discussion Note
3/2015, Mauboussin & Callahan ("Calculating Return on Invested Capital", CS 2014; "ROIC and the
Investment Process", Counterpoint Global 2022), Fundsmith Owner's Manual.

## What the evidence says

1. **Gross profitability (GP/A) is the anchor quality signal.** In Novy-Marx's seven-way horse
   race (Graham, Grantham, Greenblatt ROIC, Sloan accruals, Piotroski F, defensive, GP/A) it was
   the *only* measure with significant stand-alone excess returns and subsumed most of the others
   (5.21%/yr 3-factor alpha net of costs, 1963–2013). NBIM confirmed out-of-sample globally
   (8.37%/yr, Sharpe 0.90, 1994–2015). Our panel has it (`gross_profitability_ttm`) — weight it
   heavily in composites.

2. **Combine quality and value in one integrated rank, not sequential filters or separate
   sleeves.** Joint GP/A + value ranking earned 7.4%/yr vs 3.2–3.8% for either alone and 3.5%
   for a 50/50 side-by-side mix (500 largest non-financials, 1963–2011). Today the champions
   screen treats `fcf_yield_ttm` / `ev_to_ebitda_ttm` as context only — consider folding a value
   z-score into the composite score.

3. **Leverage/safety metrics are gates, not ranking factors.** NBIM: leverage (2.06%/yr, Sharpe
   0.20) and change-in-net-debt (2.87%/yr, Sharpe 0.37) were the only quality factors *without*
   significant four-factor alphas. Keep `net_debt_to_ebitda` / `interest_coverage` as pass/fail
   thresholds; **drop `net_debt_to_ebitda` from `SCORE_WEIGHTS`** — it buys durability, not alpha.

4. **ROIC level alone is not enough.**
   - It only creates value above the cost of capital → benchmark as sector-relative ROIC
     (more robust in a screen than firm-level WACC estimates).
   - Trend/persistence carries information: Russell 3000 1990–2022, bottom→top quintile
     migrators returned ~33% TSR vs ~−11% for top→bottom; 48% of top-quintile firms persist.
     (Caveat: contemporaneous with the migration — association, not ex-ante predictability.)
   - Mean reversion is sector-dependent: staples/health care fade slowly, tech/energy fast — the
     5y ROIC floor means more in slow-fade sectors.

5. **ROIC has three known distortions worth correcting:**
   - **Goodwill**: compute ROIC both with and ex-goodwill (Cisco FY2013: 34.1% vs 125.4%).
     With-goodwill judges management's M&A record; ex-goodwill shows the underlying business's
     reinvestment economics.
   - **Expensed intangibles**: capitalizing R&D pulls extreme ROICs toward the mean (Apple
     FY2022: ~162% traditional vs ~70% adjusted). A raw high-ROIC screen mechanically flatters
     R&D-heavy names.
   - **Cash taxes**: NOPAT = EBITA − cash taxes (provision adjusted for the deferred-tax delta,
     plus the debt tax shield) is financing-neutral, unlike provision-based NOPAT.

6. **ROIIC (incremental ROIC)**: rolling 3–5y windows only (1-year is hopelessly noisy — Cisco's
   1y ROIICs spanned +304% to −778% vs a stable 47% on 3y), never benchmark against WACC, and
   guard small capital deltas. Our `incremental_roic_5y` already matches this construction,
   including the 2% minimum-capital-growth floor.

7. **Fundsmith's operational definition of a compounder** (all verified verbatim): sustained high
   return on operating capital employed *in cash*; high returns on an *unleveraged* basis (leases
   count as debt); growth = reinvesting excess cash at high incremental returns; valuation = FCF
   yield (after tax & interest, discretionary capex added back — owner earnings) vs long rates.

8. **QMJ validates the multi-dimension composite**: z-scored profitability (GPOA, ROE, ROA, CFOA,
   gross margin, low accruals), growth, and safety (low leverage, low Altman Z/Ohlson O risk, low
   ROE volatility) earns significant risk-adjusted returns in the US and 24 countries.

### Caveats the research surfaced

- The academic results are long-short factor spreads, some gross of costs — they validate
  *ranking power*, not a long-only screen's absolute edge.
- The popular *mechanism* story for GP/A ("expensed investments pollute net income") failed
  adversarial verification — treat GP/A's edge as empirical, not settled theory. Deflator choice
  (assets vs equity vs EV, Ball et al. 2015) is debated.
- Samples end 2010–2022; post-sample factor decay possible.
- **No surviving claims established numeric cutoffs** (ROIC > 15%, ND/EBITDA < 1.5x etc. are
  practitioner convention, not research-verified). Our thresholds should be calibrated by
  decile spreads on our own panel, not treated as literature-backed.
- Not covered by surviving claims: Piotroski/Mohanram/Beneish specifics, CCC evidence,
  net debt/FCF vs net debt/EBITDA, debt maturity.

## Panel review findings (current code)

- `roic_ttm`'s 4-quarter-average denominators (`avg_capital`, `avg_assets` in returns/quality/
  distress) are **not span-gated**, unlike every other multi-quarter construct. Low impact
  (the TTM numerators are gated) but inconsistent — add `span_ok(panel, 4)` guards.
- `invested_capital` subtracts **all** cash → inflates ROIC for cash-rich names and can go
  negative (→ NaN → screened out) for exactly the mega-quality names we want. Consider an
  excess-cash convention (e.g. cash above 2% of revenue) or at least document the choice.
- `income_quality_ttm` (OCF/NI) is inflated by SBC (added back to OCF, never cash). The
  `sbc_to_revenue` gate helps; an SBC-adjusted FCF metric is the clean fix.
- `interest_coverage` uses accrual `interestExpense`; `interestPaid` (cashflow parquet) catches
  capitalized-interest games.

## Recommended additions (all computable from our parquets)

Raw columns needed but not yet pulled in `build.py`: `goodwill`,
`researchAndDevelopmentExpenses`, `operatingIncome`, `accountPayables`, `retainedEarnings`,
`shortTermDebt`, `propertyPlantEquipmentNet`, `deferredRevenue`, `deferredIncomeTax`,
`interestPaid`, `incomeTaxesPaid`, `totalLiabilities`, `workingCapital` (or compute).

### Tier 1 — return on capital refinements (research-backed)

| Metric | Formula (FMP columns) | Rationale |
|---|---|---|
| `roic_ex_goodwill_ttm` | `nopat_ttm / avg(invested_capital − goodwill)` | Mauboussin dual-view; reinvestment economics |
| `cash_roce_ttm` (CROIC) | `freeCashFlow_ttm / avg(invested_capital)` (and/or OCF-based) | Fundsmith "return on operating capital. In cash." |
| `roce_ttm` | `ebit_ttm / (totalAssets − totalCurrentLiabilities)` | Classic ROCE; robust when equity is buyback-distorted |
| `roic_vs_sector` | `roic_ttm − sector median roic_ttm` (cross-sectional, screen layer) | Value creation is relative; sector fade anchor |
| `roic_trend_3y` | `roic_ttm − roic_ttm 12 quarters ago` (span-gated) | Quintile-migration evidence |
| `rnd_adj_roic_ttm` | Capitalize R&D over 5y: asset = amortized trailing R&D; NOPAT += R&D_ttm − amortization; IC += asset | Biggest known ROIC distortion for intangible-heavy names |
| cash-tax NOPAT | `ebit_ttm − (incomeTaxesPaid_ttm)` or provision − Δdeferred + interest shield | Financing-neutral numerator |

### Tier 2 — cash generation

| Metric | Formula | Rationale |
|---|---|---|
| `fcf_conversion_ttm` | `freeCashFlow_ttm / ebitda_ttm` | Complements OCF/NI; capex-aware conversion |
| `fcf_adj_ttm` (+ margin/yield/growth) | `freeCashFlow_ttm − stockBasedCompensation_ttm` | Closes the SBC hole in OCF/NI and FCF |
| `owner_earnings_ttm` | `operatingCashFlow_ttm − min(capex_out_ttm, depreciationAndAmortization_ttm)` | Fundsmith/Buffett maintenance-capex FCF |
| `dpo_ttm`, `ccc_ttm` (+3y change) | DPO = `accountPayables·365/cogs_ttm`; CCC = DSO + DIO − DPO | Working-capital discipline; completes existing DSO/DIO |
| `cash_interest_coverage` | `(operatingCashFlow_ttm + interestPaid_ttm + incomeTaxesPaid_ttm) / interestPaid_ttm` | Cash-based coverage |

### Tier 3 — balance sheet (gates, not ranks)

| Metric | Formula | Rationale |
|---|---|---|
| `net_debt_to_fcf` | `netDebt / freeCashFlow_ttm` | Years-to-repay; harsher than EBITDA for capex-heavy names |
| `net_debt_change_3y` | `(netDebt − netDebt 12q ago) / totalAssets 12q ago` | NBIM deterioration flag (complements `debt_buildup_3y`) |
| `st_debt_share` | `shortTermDebt / totalDebt` | Maturity-wall proxy (only maturity signal in our data) |
| `altman_z` | 1.2·WC/TA + 1.4·RE/TA + 3.3·EBIT/TA + 0.6·MC/TL + 1.0·Rev/TA | QMJ safety input; distress gate for both screens |

### Tier 4 — composites & agent-context columns

- **Quality z-score composite + integrated quality×value rank** (screen layer, cross-sectional
  at `as_of` — not panel columns): QMJ-style z-scores, value z-score folded in per finding #2.
- **Piotroski F-score** — all 9 components computable; useful summary feature for the agent swarm.
- Context columns for the AI-agent stage (cheap, no gating): `rnd_to_revenue_ttm`,
  `goodwill_to_assets`, `operating_margin_ttm` (+ trend), `deferred_revenue_growth_yoy`,
  `capex_to_depreciation`.

## Suggested sequencing

1. Fix span-gating on averaged denominators; decide the invested-capital cash convention.
2. Add Tier 1 + `fcf_adj` (new raw columns → new metric functions → rebuild panel).
3. Move leverage metrics out of champions `SCORE_WEIGHTS`; fold value into the composite.
4. Add Tiers 2–4; calibrate all thresholds via decile spreads on our own panel history.
