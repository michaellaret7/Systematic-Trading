# Junk Shorts — screener methodology

**Goal:** the Cashflow Champions inverse — find businesses that persistently earn returns
below their cost of capital, generate weak or negative cash flow, carry heavy debt that is
not funding any growth, and show accounting red flags. Candidates for a short book, not
merely "not champions."

**Code:** `src/systematic_trading/screeners/junk_shorts/`
**Build:** `uv run python -m systematic_trading.screeners.panels.fundamentals.build` — the
panel is shared with Cashflow Champions; one build feeds both screens.
**Input:** `s3://<S3_BUCKET>/screeners/fundamentals_panel.parquet` (the shared metrics panel)
**Layering:** see `docs/screeners/architecture.md` for the panels/screeners/shared split.

## Why this is not a sign-flipped Cashflow Champions

1. **Ratio definedness.** The champions ratios blank out (`_safe_ratio` → NaN) exactly where
   a short screen must see: `net_debt_to_ebitda` is NaN when EBITDA ≤ 0, `income_quality`
   is NaN for loss-makers, CAGRs need positive endpoints. Every gated junk metric is
   therefore **asset-denominated** (total assets are always positive): `fcf_to_assets_ttm`,
   `debt_to_assets`, `debt_buildup_3y`. Related fix: the effective tax rate falls back to 0
   for pre-tax loss-makers, so NOPAT keeps EBIT's sign and ROIC stays defined for them.
2. **NaN semantics stay "exclude."** Missing data is not evidence of junk. NaN still fails
   every gate, which makes each gate double as a complete-data guard: the screen only
   returns companies whose badness is *measurable* over the full 5-year window.
3. **Shorts carry risks longs don't.** Hence eligibility guards that are not junk signals:
   a market-cap floor (borrowability, squeeze risk) and a sector exclusion (financials and
   REITs would flood the ranking because ROIC/EBITDA/accruals are ill-defined for them).

## Pillars, formulas, and default thresholds

### Eligibility guards (not junk signals)

| Guard | Default |
|---|---|
| `marketCap` | ≥ $500m |
| `sector` | not Financial Services / Real Estate / Utilities (FMP company-screener sectors, merged at build time; sectors are near-static so no meaningful look-ahead) |

Financials and REITs are excluded because ROIC, EBITDA, and accruals are ill-defined for
them. Utilities are excluded for the opposite reason: the metrics compute fine but
*structurally* read as junk — low regulated ROIC, heavy debt, capex-driven negative FCF —
while rate-regulated monopolies are among the worst possible shorts. Without this exclusion
utilities were the majority of the passing list.

Rows with no sector (symbol missing from the profile pull) stay in — absence of data is not
evidence the company is a financial.

### 1. Returns on capital — persistently poor

| Metric | Formula | Default |
|---|---|---|
| `roic_ttm` | same construction as champions | ≤ 6% |
| `roic_ceiling_5y` | **maximum** TTM ROIC over the trailing 20 quarters (mirror of the champions' floor) | ≤ 10% |

The ceiling is the load-bearing test: the *best* quarter-TTM ROIC in five years never
reached the cost of capital — this is not a cyclical at trough, it is a business that
structurally cannot earn its keep (Mauboussin's persistence evidence cuts both ways: the
bottom ROIC quintile is as sticky as the top).

### 2. Cash generation — weak or negative

| Metric | Formula | Default |
|---|---|---|
| `fcf_to_assets_ttm` | FCF_ttm ÷ avg total assets | ≤ 3% |
| `fcf_positive_quarters_5y` | count of positive-FCF quarters in the trailing 20 | ≤ 18 |

Asset-denominated FCF replaces FCF margin so near-zero-revenue names stay measurable.

### 3. Debt — heavy, poorly covered, not funding growth

| Metric | Formula | Default |
|---|---|---|
| `debt_to_assets` | total debt ÷ total assets | ≥ 25% |
| `interest_coverage` | EBIT_ttm ÷ interest expense_ttm (negative EBIT ⇒ negative coverage, passes naturally) | ≤ 5 |
| `debt_buildup_3y` | (total debt − total debt 12 quarters ago) ÷ total assets then | ≥ −2% |
| `revenue_growth_years_5y` | of the last 5 YoY TTM revenue checks, how many were up | ≤ 4 |

The `debt_buildup_3y` × `revenue_growth_years_5y` pair is the "debt that is not helping the
company grow" test: leverage rising or flat while the top line stagnates — borrowing to
stand still. Net-debt/EBITDA is deliberately absent (undefined for negative EBITDA).

### 4. Red flags and fragility (score-only, no hard gates)

Red flags are good at *ranking* badness but individually too noisy to be entry
requirements — the inverse of the champions design, where they act as vetoes.

| Metric | Junk direction |
|---|---|
| `accruals_ratio_ttm` | high — paper earnings ahead of cash (Sloan) |
| `dso_change_3y` | rising — receivables outrunning revenue (Beneish DSRI) |
| `dio_change_3y` | rising — days inventory outstanding vs. 12 quarters ago; inventory building against flat sales (new metric, inventory analogue of the DSO flag) |
| `share_change_3y` | rising — serial dilution funding the losses |
| `current_ratio` | low — current assets ÷ current liabilities (new metric) |
| `cash_runway_quarters` | low — cash & short-term investments ÷ quarterly TTM burn; NaN (skipped) when FCF is positive (new metric) |

## Composite score

Same rank-percentile machinery as champions (`screeners/shared/screen.py`), junk polarity: 100 = the
most shortable name in the cross-section. Inputs: ROIC, ROIC ceiling, FCF/assets, interest
coverage, current ratio, cash runway (lower = more junk) and debt/assets, debt buildup,
accruals, ΔDSO, ΔDIO, share dilution (higher = more junk). `∞` coverage (debt-free,
profitable) naturally ranks as least-junk.

Default criteria currently pass ~18 of ~1,510 non-excluded names (July 2026). Junk at $2bn+
is naturally scarcer than quality; the intersection of eight gates is kept deliberately
tight because a short book wants precision over recall.

## Known limitations

- **Survivorship bias is worse for shorts than longs.** The universe is today's $2bn+
  survivors; delisted bankruptcies — the short screen's biggest historical winners — are
  absent. Historical `screen(as_of=...)` cross-sections are only useful for comparative
  tests (threshold A vs. B) and spot-checking that later blowups were flagged; absolute
  backtest performance will be badly understated.
- **Borrow cost, short interest, and squeeze risk are not modeled.** The market-cap floor
  is a crude proxy. A live short book needs borrow-availability data before sizing.
- **Negative invested capital blanks ROIC.** A zombie with negative equity (accumulated
  losses exceeding paid-in capital) has undefined ROIC and falls out at the ROIC gates even
  though it is precisely junk. The debt/coverage/cash gates catch most of these; a
  dedicated negative-equity flag is a possible future addition.
- **Sector data is current-day.** The sector map comes from today's FMP company screener;
  symbols that left the $500m+ active universe carry NaN sector and are retained.
- **Champions limitations inherit** (lease-accounting discontinuity, history-depth warm-up,
  quarterly cadence) since the panel is shared.

## Key sources

- Mauboussin, *Death, Taxes, and Reversion to the Mean* — ROIC persistence holds in the
  bottom quintile too.
- Sloan (1996) — highest-accrual decile underperforms by ~10%/yr: the short side of the
  accrual anomaly.
- Beneish (1999) — DSRI/inventory-buildup components of the M-Score.
- Campbell, Hilscher & Szilagyi (2008) — distressed-stock underperformance: leverage,
  cash burn, and low profitability jointly predict failure.
- Asness, Frazzini & Pedersen, *Quality Minus Junk* — the junk leg of QMJ motivates
  rank-composite scoring on the short side.
