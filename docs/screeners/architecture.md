# Screeners — architecture

The screener layer separates three concerns so that adding a screener is cheap,
adding a metric is cheap, and adding a whole new data source is contained:

```
src/systematic_trading/screeners/
  __init__.py               # SCREENERS registry: name -> screener package
  shared/
    screen.py               # panel-agnostic machinery: snapshot-at-date, staleness,
                            #   sector exclusion, criteria gating, rank scoring, run_screen()
  panels/                   # panel families — each owns ONE parquet + its metrics
    fundamentals/
      constants.py          #   statement column lists, PANEL_KEY, window/staleness guards
      metrics.py            #   the metric library (TTM, ROIC, accruals, distress, ...)
      panel.py              #   build_panel + panel_uri/load_panel
      build.py              #   runnable job -> s3://<bucket>/screeners/fundamentals_panel.parquet
  csf_champions/            # a screener: opinions only
    constants.py            #   DEFAULT_CRITERIA, SCORE_WEIGHTS, PREVIEW_COLUMNS
    screen.py               #   merge criteria defaults, call shared run_screen
  junk_shorts/              # same shape (plus EXCLUDED_SECTORS)
```

## The three layers

**Facts vs. opinions is the core split.** A metric (`roic_ttm`, `debt_to_assets`) is a
fact about a company and lives in a panel; a screener is an opinion about facts
(thresholds, score polarity) and owns no computation.

1. **`shared/`** — machinery that works on *any* panel. It assumes only the panel
   contract below. No panel- or screener-specific knowledge ever goes here.
2. **`panels/<family>/`** — one data source/shape per family, one parquet per family,
   computed once by one build job. All screeners over that family read the same file.
3. **`<screener>/`** — two files: constants (the opinions) and a ~15-line `screen()`.

## The panel contract

A panel is a DataFrame/parquet with:

- one row per `(symbol, date)`
- an `available_from` timestamp — when the row became publicly knowable
  (point-in-time discipline: screening `as_of=X` only sees rows public at X)
- numeric metric columns; optionally a `sector` column if screeners need exclusions

Anything meeting this contract can be screened by `shared.run_screen` unchanged.

## The screener contract

A screener package exposes:

- `screen(panel=None, as_of=None, criteria=None) -> DataFrame` — loads its panel when
  none is passed, merges criteria overrides over `DEFAULT_CRITERIA`, calls `run_screen`
- `DEFAULT_CRITERIA` — keys are `<metric_column>_min` / `<metric_column>_max`;
  NaN metrics fail every check, so gates double as complete-data guards
- `SCORE_WEIGHTS` — metric -> +1/-1 for the percentile-rank composite (0-100)
- `PREVIEW_COLUMNS` — columns the post-build preview prints

and is registered in the `SCREENERS` dict in `screeners/__init__.py`.

## Adding things

**A new screener** (new opinion, existing facts):
1. New package with `constants.py` + thin `screen.py` (copy `junk_shorts/` as template).
2. Register it in `SCREENERS`.
3. Tests + a methodology doc under `docs/screeners/`.
No new data infrastructure; the panel build's preview picks it up automatically.

**A new metric** (new fact): add it to the panel family's `metrics.py`, rebuild the
panel, and it is available to every screener. Prefer asset-denominated ratios when the
metric must stay defined for loss-makers (`_safe_ratio` blanks on non-positive
denominators). When `metrics.py` approaches the 500-line cap, split it into a
`metrics/` subpackage by pillar.

**A new panel family** (new data source/shape — e.g. price/volume technicals, annual
statements, insider activity): new subpackage under `panels/` with its own constants,
metrics, panel, and build job, writing its own parquet to `screeners/<family>_panel.parquet`.
Reuse `shared/screen.py` as-is. If a second fundamentals-like family needs the
time-series helpers (`_ttm`, `_safe_ratio`, `_cagr`, span guard), lift them from
`panels/fundamentals/metrics.py` into `shared/` at that point, not before.

## Build & storage

- One build job per panel family; `uv run python -m systematic_trading.screeners.panels.fundamentals.build`
  rebuilds the fundamentals panel (rerun after each `push_fundamentals.py` refresh)
  and prints a preview of every registered screener.
- The fundamentals build also merges a `sector` column from the FMP company screener
  (sectors are near-static, so applying today's map to history is not meaningful
  look-ahead).
