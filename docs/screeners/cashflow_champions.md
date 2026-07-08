# Cashflow Champions — screener methodology

**Goal:** find businesses that earn high returns on invested capital, convert earnings into
real cash, show accounting green flags, carry little debt, and have proven they can reinvest
excess cash at attractive incremental returns — the drivers of long-run compounding. Every
test is measured over multi-year windows; nothing in this screen is a single-quarter snapshot.

**Code:** `src/systematic_trading/screeners/csf_champions/`
**Build:** `uv run python scripts/build_cashflow_champions.py` (rerun after each
`push_fundamentals.py` refresh)
**Output:** `s3://<S3_BUCKET>/screeners/cashflow_champions.parquet`

## Architecture

The screener is split into a *panel build* and a *filter*:

1. `build_panel` joins the three quarterly statement files (income, balance, cash flow) on
   `(symbol, date)` and computes, for every symbol at every fiscal quarter end, trailing-
   twelve-month (TTM) levels plus 3–5 year trend and consistency statistics. Each row carries
   `available_from` — the latest SEC `acceptedDate` across the three statements — so the panel
   is point-in-time: screening "as of 2024-06-30" only sees numbers that were public then.
2. `screen(panel, as_of, criteria)` takes each symbol's latest visible row, drops stale
   listings (no filing within 270 days), applies the pillar filters, and ranks passers by a
   cross-sectional percentile composite (`score`, 0–100).

All ratios are computed from raw statements, never taken from the FMP `ratios`/`key_metrics`
files: FMP's quarterly ratios are **single-quarter** figures, not TTM, and quarterly flow
ratios are distorted by seasonality — the exact snapshot trap this screener exists to avoid.

## Pillars, formulas, and default thresholds

NaN metrics fail their filter, so names with short or gappy history drop out instead of
sneaking through. Rolling windows are additionally invalidated when the calendar span of the
window is implausible (reporting gap guard: `lags × 98 + 40` days).

### 1. Returns on capital — high and sustained

| Metric | Formula | Default |
|---|---|---|
| `roic_ttm` | NOPAT ÷ avg invested capital; NOPAT = EBIT_ttm × (1 − effective tax rate, capped at 50%); invested capital = total debt + total equity − cash & short-term investments (financing approach, excess cash netted out) | ≥ 15% |
| `roic_floor_5y` | minimum TTM ROIC over the trailing 20 quarters | ≥ 10% |

The 15% bar is the practitioner consensus (Fundsmith-style ROCE > 15%, Compounding Quality
ROIC > 15%); the two-tier "high today AND never below ~WACC in five years" structure follows
Mauboussin's persistence evidence — demanding top-tier ROIC *every* year leaves <4% of firms,
while "consistently above the cost of capital" is what the persistence data actually supports
(Mauboussin, *Death, Taxes, and Reversion to the Mean*; *Calculating Return on Invested
Capital*, Morgan Stanley).

### 2. Cash generation

| Metric | Formula | Default |
|---|---|---|
| `fcf_margin_ttm` | FCF_ttm ÷ revenue_ttm | ≥ 5% |
| `income_quality_ttm` | operating cash flow_ttm ÷ net income_ttm | ≥ 1.0 |
| `fcf_positive_quarters_5y` | count of positive-FCF quarters in the trailing 20 | ≥ 18 |

CFO/NI > 1 is one of Piotroski's nine F-score signals; Fundsmith requires ~95%+ cash
conversion. The N-of-M positivity streak is the S&P Quality FCF Aristocrats pattern (10
consecutive positive-FCF years) adapted to our 10-year quarterly history — 18 of 20 quarters
tolerates one bad COVID-type quarter without admitting erratic cash generators.

### 3. Accounting green flags

| Metric | Formula | Default |
|---|---|---|
| `accruals_ratio_ttm` | (net income_ttm − CFO_ttm) ÷ avg total assets | ≤ +10% |
| `dso_change_3y` | days sales outstanding (TTM basis) now vs. 12 quarters ago | ≤ +15 days |
| `sbc_to_revenue_ttm` | stock-based comp_ttm ÷ revenue_ttm | ≤ 15% |

Accruals use the cash-flow-statement construction, which Hribar & Collins (2002) show is
cleaner than balance-sheet deltas (M&A/FX contamination); Sloan (1996) found the lowest-
accrual decile beats the highest by ~10%/yr, with > +10% the empirical red zone. Rising DSO
(receivables outrunning revenue) is the classic channel-stuffing flag (Beneish DSRI).
SBC > 15% of revenue is a red flag even by tech standards; these red-flag metrics act as
**vetoes** rather than ranked inputs — red flags are good at exclusion, bad at ranking.

### 4. Balance sheet

| Metric | Formula | Default |
|---|---|---|
| `net_debt_to_ebitda` | net debt ÷ EBITDA_ttm (negative = net cash; NaN if EBITDA ≤ 0) | ≤ 1.5 |
| `interest_coverage` | EBIT_ttm ÷ interest expense_ttm (∞ when profitable with no interest) | ≥ 10 |

1.5× is deliberately stricter than the generic ≤ 3× ceiling — champions shouldn't need
leverage. Coverage ≥ 10× is Fundsmith's explicit rule. Equity-denominated leverage ratios
(D/E) are intentionally absent: negative equity from big buyback programs (McDonald's, Home
Depot pattern) makes them flag exactly the wrong companies.

### 5. Sustained growth without dilution

| Metric | Formula | Default |
|---|---|---|
| `revenue_cagr_5y` | TTM revenue now vs. 20 quarters ago, annualized | ≥ 5% |
| `revenue_growth_years_5y` | of the last 5 year-over-year TTM revenue checks, how many were positive | ≥ 4 |
| `fcf_ps_cagr_5y` | TTM FCF per diluted share, 5-year CAGR | ≥ 5% |
| `share_change_3y` | diluted share count now vs. 12 quarters ago | ≤ +5% |

Growth is measured TTM-to-TTM five years apart *and* required to be persistent (4 of 5 years
up) — a company that shrank for four years and spiked in the fifth fails even if its CAGR
passes. FCF **per share** is the compounding test that survives dilution; the share-count cap
closes the SBC loophole (SBC is added back to CFO but shows up in the share count).

### 6. Compounding quality (score-only, no hard filter)

| Metric | Formula |
|---|---|
| `incremental_roic_5y` | ΔNOPAT_ttm ÷ Δinvested capital over 20 quarters; only computed when capital grew > 2% of its base (near-zero denominators explode on noise — Wall Street Prep/Mauboussin ROIIC guidance) |
| `reinvestment_rate_ttm` | (capex + acquisition outflows)_ttm ÷ CFO_ttm |
| `gross_margin_std_5y` | stddev of TTM gross margin over 20 quarters (stability ≈ moat; MSCI Quality treats low variability as a first-class factor) |

These rank companies but don't gate them: shrinking-capital compounders (heavy buybacks) have
no meaningful incremental ROIC and shouldn't fail for it.

## Composite score

Rank-percentile average (0–100) over: ROIC, incremental ROIC, FCF margin, income quality,
revenue CAGR, FCF/share CAGR (higher better) and accruals, net debt/EBITDA, gross-margin
volatility, SBC/revenue (lower better). Rank-based scoring follows O'Shaughnessy (composites
beat single metrics ~82% of the time) and AQR's Quality-Minus-Junk construction, and is
naturally robust to the fat tails hard z-scores choke on. The architecture — few hard gates
for non-negotiables, everything else ranked — is the same hybrid S&P uses for the FCF
Aristocrats, and keeps the screen from being over-constrained (six independent 30%-pass
filters would leave ~0.1% of the universe). Default criteria currently pass ~65 of ~2,080
names, inside the 30–100 sanity band.

## Known limitations

- **Financials are not excluded.** ROIC, EBITDA, and accruals are ill-defined for
  banks/insurers; in practice they fail the interest-coverage and cash-conversion gates, but
  the panel has no sector column to exclude them structurally. If FMP profile data is added
  later, exclude financials and REITs outright.
- **History depth gates the backtest window.** The fundamentals files hold ~10 years; the
  5-year consistency windows need ~6 years of warm-up, so `screen(as_of=...)` produces useful
  cross-sections from roughly 2022 onward (51 names at 2024-06-30, zero before ~2022).
- **Capital-light ROIC is numerically extreme.** VEEV/MANH/MEDP-type businesses run ROIC of
  300–600% because invested capital net of cash is tiny. The values are real, and percentile
  ranking neutralizes the magnitude; just don't read the raw ratio as a comparable intensity.
- **Lease accounting discontinuity.** ASC 842 (2019) moved operating leases onto balance
  sheets; `totalDebt` includes capitalized leases only after that, which slightly flatters
  pre-2019 ROIC/leverage within the 5-year windows that straddle it.
- **Two structural false negatives** of any quality screen: companies whose reported
  profitability is depressed by expensed growth investment (heavy R&D intangibles), and great
  cyclicals at trough earnings.

## Key sources

- Mauboussin & Callahan, *Calculating Return on Invested Capital* (Morgan Stanley) — ROIC and
  ROIIC construction, excess-cash netting, 3–5y ROIIC windows.
- Mauboussin, *Death, Taxes, and Reversion to the Mean* — ROIC persistence quintiles.
- Sloan (1996) / Hribar & Collins (2002) — accrual anomaly; cash-flow-statement accruals.
- Piotroski (2000) — F-score binary-signal design (CFO > NI, no new equity issuance).
- Novy-Marx (2013) — gross profitability; margin cleanliness/stability as quality.
- Asness, Frazzini & Pedersen, *Quality Minus Junk* — z/rank composite quality scoring.
- S&P *Quality FCF Aristocrats* methodology — consecutive-positive-FCF eligibility gate plus
  rank selection on 5-year-averaged FCF metrics.
- Fundsmith owner's manual / Terry Smith ratio set — ROCE > 15%, cash conversion ~95%+,
  interest cover ≥ 10×.
