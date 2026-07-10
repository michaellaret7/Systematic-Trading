# Short screen ("junk shorts") research: evidence review & design implications

July 2026. Deep research (multi-source, adversarially verified against primary sources) on building
a fundamental short screener — the inverse of Cashflow Champions: companies that are poor quality,
burn cash, earn low/negative returns on capital, manipulate earnings, dilute shareholders, and pile
on debt. Scope: US equities >$2bn, quarterly FMP fundamentals.

Primary sources verified verbatim: Asness/Frazzini/Pedersen QMJ (RAS 2019 / working paper),
Novy-Marx "Quality Investing" (QDoVI), Piotroski (JAR 2000), Dechow/Khimich/Sloan accruals review
(2011) + Richardson/Sloan/Soliman/Tuna (2005), Campbell/Hilscher/Szilagyi (JF 2008),
Beneish/Lee/Nichols (FAJ 2013), Cooper/Gulen/Schill (JF 2008), Pontiff/Woodgate (JF 2008),
Stambaugh/Yu/Yuan (JFE 2012). Verification stats: 109 claims extracted from 24 sources, 25
verified by 3-vote adversarial panels → 22 confirmed, 3 refuted. Practitioner-framework and
implementation-cost claims below the verification cut are labeled **[extracted, unverified]**.

## 1. The central result: the short side is where the mispricing lives — and where the frictions live

Three independent verified results say the same thing from different angles:

1. **Anomaly profits concentrate in the short leg.** Across 11 documented anomalies (CHS failure
   probability, Ohlson O-score, net stock issues, composite equity issues, total accruals, net
   operating assets, momentum, gross profitability, asset growth, ROA, investment-to-assets), the
   short legs drive the profits and are the only side with sentiment sensitivity — long legs show
   *no* significant sentiment relation (Stambaugh/Yu/Yuan, JFE 2012, verified 3-0). Mechanism:
   Miller (1977) — short-sale impediments let overpricing persist where underpricing can't.

2. **Causal confirmation.** The SEC's Reg SHO pilot (2005–07) randomly relaxed shorting
   constraints; anomaly long-short returns fell ~72bp/month on pilot stocks and the *entire*
   effect came from the short legs (Chu/Hirshleifer/Ma, JF 2020) **[extracted, unverified]**.

3. **Junk underperforms on its own, risk-adjusted.** The lowest-quality US decile (1956–2012):
   CAPM alpha −0.53%/mo (t=−4.62), 4-factor alpha −0.56%/mo (t=−6.24); globally −0.61%/mo; the
   QMJ factor is positive in 23 of 24 developed countries (verified 3-0 against QMJ Table IV).

**The catch, stated up front:** the junk decile's *raw* excess return was slightly **positive**
(+0.15%/mo at beta 1.28). Same for high asset growth (+5%/yr raw) and high accruals (+10.2%/yr
raw). The short side earns **alpha, not absolute declines** — an outright unhedged short book of
junk names loses money in bull markets. This validates our screener as the short leg of a
long/short (or beta-hedged) construct, not a standalone money-maker.

## 2. Signal-by-signal evidence

Ranked by verified strength *in a >$2bn universe* — the small-cap concentration of many anomalies
is the single most important adjustment to headline academic numbers.

### 2.1 Low gross profitability — the anchor (verified, high confidence)

Of seven quality strategies horse-raced 1963–2013 (Graham G, Grantham quality, ROIC, Sloan
accruals, Piotroski F, defensive, GP/A), **only gross profitability had a significant standalone
excess return** (2.7%/yr; FF3 alpha 5.21%/yr, t>4). Within the Russell 1000 it is the *only*
signal retaining consistently significant alpha after controlling for FF factors and every rival
(t=2.99–4.48 vs rivals' t=−1.20–1.36) — it subsumes ROIC, F-score, and Grantham quality in large
caps (Novy-Marx QDoVI Tables 2/5, verified 3-0). Mirror of the champions finding: **low GP/A
should anchor the short screen's quality dimension**, exactly as high GP/A anchors the long side.

One exception survived the horse race: **Sloan accruals retains significant large-cap alpha vs
GP/A** (2.30%/yr, t=2.14) and is *negatively* correlated with it (−0.26). Novy-Marx explicitly
argues accruals is not a quality measure at all — it's a distinct, complementary signal. So GP/A
and accruals are the two pillars, not substitutes.

### 2.2 Earnings manipulation: Beneish M-score (verified, high confidence)

The strongest genuinely-incremental finding of the whole research pass. Higher
manipulation-probability firms earn lower subsequent returns **out-of-sample** (model fit 1982–88,
returns tested 1993+), and the effect holds **within every decile sorted on size, book-to-market,
momentum, accruals, and short interest** (Beneish/Lee/Nichols, FAJ 2013, verified 3-0). It is not
subsumed by value, momentum, size, Sloan accruals, or existing short positioning.

Mechanism: M-score forecasts *future accrual reversals*, and it is **strongest among low-accrual
stocks that a plain accruals screen would classify as safe** (−19.8% 12-month size-adjusted spread
in the lowest-accrual quintile). M-score catches shorts a standalone Sloan filter misses. All
eight components (DSRI, GMI, AQI, SGI, DEPI, SGAI, LVGI, TATA — Beneish 1999 convention) are
plain statement ratios. Caveats: sample ends ~2007; apply a McLean-Pontiff-style post-publication
haircut (~35–58%).

### 2.3 Accruals / ΔNOA — manipulation-adjacent balance-sheet bloat (verified, high confidence)

Sloan hedge return 11%/yr (1970–2007 replication), with the high-accrual **short decile the
extreme performer** (10.2% raw t+1 vs 21.2% low-accrual). Broadening from current accruals to the
**change in net operating assets** (Richardson/Sloan/Soliman/Tuna 2005) raises the hedge return to
18%/yr (t=14.91) because long-term accruals catch WorldCom-style expense capitalization. High-
accrual firms are disproportionately subsequent SEC-enforcement targets (receivables and inventory
the most-manipulated accounts) and their accruals reverse sharply negative — this is a direct
earnings-manipulation-risk filter, not just a sentiment proxy. (All verified 3-0 against a review
co-authored by Sloan himself.)

**Failure modes (also verified):** concentrated in small, thinly-traded, volatile stocks, and the
simple anomaly **decayed sharply around 2000** (Green/Hand/Soliman: "no longer reliably positive")
— plausibly arbitraged away. Prefer the ΔNOA / percent-accruals variants, which retained more
power. Sector-dependence **[extracted, unverified]**: positive in 29 of 32 industries, strongest
where working capital dominates assets (construction, toys, computers), **fails entirely in drugs,
mining, and energy**; inventory accruals are the most robust component.

### 2.4 Net share issuance — dilution (verified, high confidence)

Post-1970, net share issuance negatively predicts returns with statistical significance
**exceeding size, book-to-market, and momentum individually** (Pontiff/Woodgate JF 2008, verified
3-0). Replicated internationally (McLean/Pontiff/Watanabe 2009), pervasive across size groups
(Fama/French 2008), and survives the Hou/Xue/Zhang replication purge under value-weighting —
investment-category anomalies had the highest replication rate (94.7%). Computable purely from
split-adjusted share counts. **This is the best-suited signal for a large-cap screener after
GP/A and M-score.** Qualifications: no effect pre-1970; ~35% post-publication decay.

### 2.5 Distress probability — CHS (verified, high confidence)

Since 1981, high-modeled-failure-probability stocks earn **anomalously LOW returns** despite
higher betas and volatility (Campbell/Hilscher/Szilagyi JF 2008, verified 3-0). Distress is a
short signal, not a risk premium. Failure predictors: higher leverage, lower profitability, lower
market cap, lower past returns, higher return volatility, **lower cash**, **higher market-to-book**
(glamour-priced distress — counterintuitive and useful: expensive-looking distressed names are the
worst), lower price per share. Holds in all size quintiles but strongest in small,
low-institutional-ownership, hard-to-borrow names — expect attenuation at >$2bn. At longer
horizons (relevant to quarterly rebalancing) the persistent inputs — market cap, M/B, volatility —
gain predictive weight over transient accounting items.

### 2.6 Asset growth (verified headline, medium confidence for our universe)

Lowest asset-growth decile ~18%/yr VW raw vs ~5% for the highest (1968–2003); risk-adjusted
low-minus-high ~8%/yr VW, ~20%/yr EW (Cooper/Gulen/Schill JF 2008, headline verified 3-0). **But
the two claims that mattered most for us were refuted in verification** (see §8): the large-cap
robustness claim (10% VW large-cap alpha) went 1-2 and the "asset growth subsumes the anomaly
family" claim went 0-3. Treat as a documented full-cross-section signal whose large-cap strength
is unproven; it is also highly correlated with ΔNOA, so it partially duplicates §2.3. The VW short
leg fails ~29% of years — junk-rally exposure. Useful decomposition **[extracted, unverified]**:
within *large* firms, the strongest component is **stock-financing growth** — which loops back to
§2.4 dilution.

### 2.7 Piotroski low F-score (verified — but weakest fit for our universe)

Within high-B/M stocks 1976–96: 23%/yr long-high/short-low, 43.2% two-year market-adjusted spread,
low-F firms −14.5%; low-F firms >5x more likely to delist for performance reasons within two years
(F=0: 7.0% vs F=8: 1.7%), nearly monotonic (all verified 3-0). **Critical caveat, from the paper's
own abstract:** the power is concentrated in small/medium firms with low turnover and no analyst
coverage — weakest exactly in a >$2bn universe — and it was defined on annual data within value
stocks only. Novy-Marx independently shows F-score's large-cap alpha is subsumed by GP/A. Keep the
F-score as a cheap summary feature / agent context column, not a core ranking factor.

## 3. Cross-signal structure: MGMT vs PERF **[extracted, unverified]**

Stambaugh/Yuan (RFS 2017) find the 11 anomalies comove in exactly two clusters:

- **MGMT** — things management directly controls: net stock issues, composite equity issues,
  accruals, net operating assets, asset growth, investment-to-assets.
- **PERF** — performance outcomes: distress, O-score, momentum, gross profitability, ROA.

Short-leg betas are ~2x long-leg magnitudes in both clusters (−0.46 vs 0.20 MGMT; −0.49 vs 0.30
PERF). This is a ready-made template for the composite: **one dilution/bloat dimension (MGMT) +
one deterioration dimension (PERF) + one manipulation dimension (M-score, incremental to both)** —
rather than ten correlated ratios pretending to be ten signals.

## 4. Implementation reality check — where short screens die

This section is the biggest asymmetry vs the long-side research, and most of it sits below the
verification cut — labeled accordingly, but the sources are top-tier journals.

- **Borrow fees eat everything on average.** Across 162 anomalies, the average long-short return
  is +0.14%/mo gross but **−0.01%/mo net of borrow fees**; anomalies aren't profitable even gross
  if the 12% of stock-dates with high fees are excluded (Muravyev/Pearson/Pollet, JF 2025)
  **[extracted, unverified]**. Similarly, anomalies "effectively disappear within the 80% of
  stocks that have low short fees" (Drechsler & Drechsler 2014) **[extracted, unverified]**.
  Read carefully, this cuts both ways for us: a >$2bn easy-to-borrow universe has *cheap*
  implementation but captures *less* of the documented short alpha. The Reg SHO decomposition
  quantifies it: short-leg effect 88bp/mo in small stocks vs 37bp in large; 96bp in
  hard-to-short vs 30bp in easy **[extracted, unverified]**.
- **Squeeze risk is a utilization phenomenon, not a universal one.** At utilization ≤25% (~3 of 4
  stocks) an all-lender squeeze occurs ~once every 40 years; at ≥90% utilization, ~once every 11
  days; squeeze costs eliminate >2/3 of the returns to shorting the highest-utilization names
  (JFQA 2024) **[extracted, unverified]**. Borrow fee itself out-predicted all 102 anomalies
  2006–19 (Engelberg et al. 2020, cited therein). For a $2bn+ fundamental screen this is mostly
  reassuring — but a utilization/borrow-fee overlay at execution time is the obvious guard.
- **Regime dependence is verified and large.** 78% of short-leg profits across the 11 anomalies
  occur in months following above-median sentiment; the combined short leg earns **−68bp/mo excess
  after high sentiment vs +65bp/mo after low sentiment** — a 132bp/mo swing (Stambaugh/Yu/Yuan,
  verified 3-0). The screen's worst environment is a low-sentiment recovery — the 2009-style junk
  rally. QMJ's flip side (verified): short-junk behaves like a **crisis hedge** (flight to quality,
  mild positive convexity in crashes) but is structurally short high-beta small stocks in melt-ups.
- **A sobering large-cap backtest.** Shorting top-decile low-quality and high-volatility S&P 500
  stocks 2005–22 (monthly rebalance, 10bps costs) produced *negative* excess returns; low-growth
  and low-momentum shorts ~zero; all the multi-factor "lousy stock" portfolios crashed in the 2009
  recovery; Tesla rose >2000% after 2020 on abysmal fundamentals (CFA Institute blog, 2023)
  **[extracted, unverified — blog-quality source, but consistent with §2's attenuation
  findings]**.
- **Post-publication decay is pervasive.** McLean-Pontiff ~35–58% haircut; accruals specifically
  became unreliable post-2000; most samples end 2003–2013. Historical magnitudes are ceilings.
- **High idiosyncratic volatility amplifies overpricing** among already-overpriced stocks (it's an
  amplifier, not a standalone signal) — and the IVOL effect is itself sentiment-dependent
  (Stambaugh/Yu/Yuan JF 2015) **[extracted, unverified]**.

## 5. Sector and cyclical false positives

- **Financials look structurally junky on asset-scaled metrics.** Verified within QDoVI: financial
  firms hold large financial asset bases with little tangible capital, so GP/A, Grantham quality,
  and accrual measures scaled by assets misclassify them; Novy-Marx ranks financials separately.
  Corroborates our existing exclusion of financials/REITs.
- **Accruals fails entirely in drugs, mining, energy** and is strongest in working-capital-heavy
  industries **[extracted, unverified]** — sector-aware weighting (or at least awareness) matters
  even after exclusions.
- **Our own v1 lessons are corroborated, not contradicted:** utilities exclusion (regulated
  low-ROIC + leverage + capex burn is their business model, not distress) and trough-cyclicals as
  the structural false positive (2021 cross-sections polluted by pandemic-trough travel/leisure).
  Nothing in the verified literature resolves sector-neutral ranking vs exclusion — it remains an
  open design choice (see §9).
- Note the CHS twist: distress pairs with **high** M/B. A screen that requires "expensive AND
  deteriorating" (rather than cheap-and-bad) is closer to what the distress evidence — and Chanos
  — actually describe. Trough cyclicals tend to look *cheap* on M/B, so an expensiveness condition
  is also a partial cyclical filter.

## 6. Practitioner frameworks — all convention, none verified

No Chanos/Fearon/forensic claim survived to the verified set (sources are interviews, books,
blogs). Extracted material, useful as design inspiration and agent-layer heuristics only:

**Chanos (Kynikos)** — "bad business combined with bad numbers": deteriorating fundamentals masked
by aggressive-but-legal accounting; **valuation is explicitly the last factor considered**. Core
forensic tells: earnings growing while operating cash flow deteriorates (gain-on-sale accounting,
hidden cash burn); serial acquisitions substituting for organic growth (HP: ~$37bn of deals, flat
revenue); credit-driven asset inflation where asset cash flow can't service the debt. Leverage
makes the short asymmetric: at 90% debt / 10% equity, a 50% equity decline is only 5% of the
enterprise. His failure modes: borrow disappears once the thesis is visible; open-ended growth
stories "have a life of their own" (shorted AOL at $8, covered at $80). Process: read filings
backwards in time, track disclosure-language changes, never meet management; marquee investors on
the register are *not* disconfirming ("the largest frauds always have marquee investors").

**Fearon ("Dead Companies Walking")** — six failure patterns, all qualitative: learning only from
the recent past; over-reliance on a success formula; misreading/alienating customers; falling for
a mania; failing to adapt to tectonic industry shifts; management removed from operations. His
explicit warning: the decisive failure signals are qualitative — a fundamentals-only screen has a
capability ceiling. Quantifiable proxies from his material: PIPE financings as late-stage
distress/dilution; serial M&A with declining gross margins.

**Forensic red-flag conventions** (pre-2003 auditing literature): NI rising while OCF falls;
receivables >15% of sales / inventory >25% of COGS; receivables or inventory growing faster than
sales (≈ Beneish DSRI/AQI components); NI growth wildly disproportionate to revenue growth
(HealthSouth: +500% NI on +5% revenue); SAS 82 lists cash-flow inability plus pressure to raise
capital as formal fraud risk factors. These are the qualitative ancestors of M-score — the
research-verified way to hold them is §2.2/§2.3, not the raw thresholds.

**What survives translation to our panel:** NI-vs-OCF divergence (we have `income_quality_ttm` —
here its *low* tail is the signal), receivables/inventory growth vs sales (DSO/DIO trends exist;
M-score components formalize them), serial-acquirer goodwill buildup (`goodwill_to_assets` trend),
external-financing dependence (issuance + debt buildup + negative FCF simultaneously — an
extracted SAS 82 factor and the exact MGMT cluster).

## 7. Design implications for our screener

1. **Composite over single signal, three dimensions.** Verified incrementality results (M-score
   holds within accrual deciles; accruals retains alpha vs GP/A at −0.26 correlation) point to:
   **deterioration** (low GP/A anchor, falling margins/turnover, distress inputs) +
   **bloat/dilution** (ΔNOA or percent-accruals, net share issuance, asset growth, debt buildup) +
   **manipulation** (M-score). This mirrors MGMT/PERF plus Beneish.
2. **Signals to weight up for $2bn+**: low GP/A, M-score, net issuance — the only three with
   verified or well-corroborated large-cap efficacy. Weight down: F-score, simple Sloan accruals
   (use ΔNOA instead), raw asset growth (large-cap claim refuted).
3. **Expect spread alpha, not falling prices.** Every verified short decile had positive raw
   returns in normal markets. The screen's output is the short leg of a hedged book; sizing and
   hedging live outside the screener, but the doc of record should never sell it as "these stocks
   go down".
4. **Regime awareness is legitimate, timing is not (yet).** The sentiment result is verified and
   huge (132bp/mo swing) but turning it into a live exposure dial is a separate research project;
   at minimum, backtests must report performance in junk-rally windows (2009, 2020-21) separately.
5. **Prefer "expensive and deteriorating" over "cheap and bad".** CHS's positive M/B loading +
   Chanos convention agree; also mitigates the trough-cyclical false positive.
6. **Keep sector exclusions; add sector-awareness to accrual-type metrics.** Financials/REITs/
   utilities exclusions corroborated; drugs/mines/energy weaken accrual signals.
7. **Point-in-time hygiene matches what we already built.** The literature's convention (≥4-month
   lag on annual data; quarterly data only after the reporting date) is exactly our
   `filingDate`-based cross-section — no change needed, but it's now literature-backed.
8. **Quarterly adaptation is untested.** F-score, accruals, issuance, asset growth were all
   defined on annual data. TTM / same-quarter-YoY adaptations are our own implementation choice —
   calibrate by decile spreads on our panel (same discipline as the champions thresholds), not
   literature numbers.

### Computability from the FMP quarterly panel

| Signal | Construction (panel/raw columns) | Status |
|---|---|---|
| Low gross profitability | `gross_profitability_ttm` (low tail) | exists |
| ΔNOA / percent accruals | NOA = (totalAssets − cash) − (totalLiabilities − totalDebt); ΔNOA₄q / lagged assets | new metric, columns exist |
| Beneish M-score (8 ratios) | receivables, revenue, COGS, currentAssets, PP&E, D&A, SG&A, debt, WC accruals | new metric, needs a few raw columns |
| Net share issuance | Δ split-adjusted shares (weightedAverageShsOut) YoY; cross-check cashflow issuance/buyback lines | new metric |
| Asset growth | ΔtotalAssets YoY | trivial |
| Debt buildup | exists (`debt_buildup_3y`) — NBIM net-debt-change finding from the quality research applies | exists |
| Distress (CHS-style) | NIMTA, TLMTA, CASHMTA from panel + marketCap; EXRET/SIGMA/price need the future price panel | partial — fundamentals half now |
| F-score / Altman Z | agent-context columns (distress group has Altman planned) | context only |
| Cash burn | negative `fcf_ttm` + short runway (cash / TTM burn) + external-financing dependence | new metric, columns exist |

## 8. Refuted in verification (do not rely on)

- **The QMJ variable recipe as commonly summarized** (0-3): the exact construction must be taken
  from the paper itself, not secondhand summaries — safety includes *market-based* inputs (beta,
  IVOL) that a pure-fundamentals screener can't fully replicate.
- **Asset growth's large-cap robustness** (1-2): the "10% VW large-cap alpha" claim did not
  survive.
- **Asset growth subsuming the growth/accruals anomaly family** (0-3): it does not dominate;
  keep ΔNOA and issuance as separate dimensions.

## 9. Caveats & open questions

- All figures are gross academic portfolio returns — no borrow fees, no transaction costs, no
  squeeze costs; and several key "short" results are relative underperformance of stocks with
  positive raw returns.
- Most samples end 2003–2013; post-publication decay (~35–58%) applies on top of large-cap
  attenuation (1–2%/yr for most quality measures). Stack both haircuts when setting expectations.
- The entire practitioner section (§6) is unverified convention; the sector-structural material in
  §5 beyond the financials point is extracted-but-unverified.
- Open: sector-neutral ranking vs exclusion (unresolved by the literature); live post-2010
  large-cap short-leg performance of the composite (Chen-Zimmermann open anomaly data could answer
  this); which execution overlays (utilization, borrow fee, momentum filter) reduce blowups
  without destroying the signal; whether any activist-short-report signal has academic validation.
- Survivorship: as with champions, deep-history backtests on today's universe are for comparative
  tests (threshold A vs B, decile spreads), not absolute performance — and the short side is
  *more* sensitive to this, since the worst names delist out of the universe.
