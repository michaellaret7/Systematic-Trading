# Portfolio sleeve allocation: long-only + long/short

How to think about splitting the portfolio between the champions long-only
strategy and a future long/short sleeve. Written July 2026, before the L/S
strategy exists — revisit once it has a live track record.

## 1. Assign each sleeve a role first

The champions long-only book is the return engine — roughly beta 1, fully
exposed, its edge compounds over years. The L/S sleeve's job is *not* to
maximize return; it is to add a return stream that doesn't depend on the market
going up, and to dampen drawdowns. Framed that way, "how much to allocate"
becomes "how much market exposure do I want to dilute, and how much do I trust
the second strategy" — not "which strategy is better."

## 2. Size by risk contribution, not capital

A true market-neutral L/S book typically runs ~5–10% annualized vol; a
concentrated long-only equity book runs 15–20%+. An 80/20 capital split is
therefore more like a 93/7 **risk** split — the L/S barely registers.

Rough rule: the L/S sleeve's share of portfolio risk ≈
(L/S capital × L/S vol) vs (long capital × long vol).

For the L/S sleeve to meaningfully smooth the ride it needs more capital than
intuition suggests — something like 30–40% — or it must run higher gross
exposure internally.

## 3. Trust is earned: start smaller than the target

As of this writing the evidence base is a two-year, survivorship-flattered
simulation on the long side and no live track record on the short side. Shorts
also fail differently (trough cyclicals as false positives, squeeze risk,
borrow costs — see the junk-shorts lessons).

Seed the new sleeve at 10–20%, run it live (paper first) for a couple of
quarters, and scale toward the risk-based target only once it demonstrates:

1. It makes money on its own.
2. Its returns are actually uncorrelated with the long book in the same weeks —
   market-neutral on paper often isn't in a stress; verify with live data.

## 4. Define the sleeves in exposure terms, explicitly

Per sleeve, write down: capital %, gross exposure, net exposure. Starting
point:

| Sleeve               | Capital | Gross     | Net    |
| -------------------- | ------- | --------- | ------ |
| Champions long-only  | 80%     | 100%      | +100%  |
| Long/short           | 20%     | 100–150%  | ~0     |

Combined portfolio beta ≈ 0.8, with a second return stream on a different
clock.

Also set a rebalancing policy between sleeves: quarterly back to target, or
drift bands (rebalance when a sleeve is ±5 points off target). Without a
written policy the winning sleeve silently eats the portfolio.

## 5. Mechanics in this stack

`live.py` runs multiple strategies in one `Trader`, but they share one Alpaca
account's cash — nothing stops sleeve A from spending sleeve B's buying power.
Two clean options:

- **Separate Alpaca accounts per sleeve** (cleanest accounting; trivial with
  paper accounts).
- One account with each strategy sized against its own budget, plus a hard
  rule that neither reads `self.cash` as "mine."

Decide before the second strategy exists — it shapes how it gets written. Note
the sleeves will sometimes hold opposite positions in the same name (champions
long X, L/S short X); in one account those net out at the broker and corrupt
both strategies' books. Separate accounts sidestep that entirely.

## 6. Warning on the shorter-term component

Mixing horizons is genuinely good (different return clock = real
diversification), but shorter-term means more trades, and the edge must clear
costs on every trade. The champions edge only has to be right over quarters; a
weekly-turnover L/S edge has to be right net of spread, borrow, and slippage
constantly. Backtests understate exactly those costs — which is why
seed-small-and-verify-live matters most for this sleeve.

## Execution plan (decided July 2026)

Single brokerage account with **dynamic universe exclusion**, not separate
accounts (Alpaca allows one live retail account per person; multiple paper
accounts cover the proving phase).

- **Universe exclusion, every L/S cycle:** define the technical universe,
  screen it, then subtract champions' current holdings (from the DynamoDB
  trade book). Both directions — the L/S neither shorts nor longs a champions
  name — so every account position has exactly one owning strategy. The L/S
  universe (technicals/price action, much broader than the US-fundamentals
  champions universe) loses almost nothing to this rule.
- **Order-time re-check:** the sleeves run on different clocks, so a name can
  enter the champions book between L/S screening and execution. Immediately
  before submitting any L/S order, look the name up against the champions book
  again and drop the order on a hit. The universe filter does 99% of the work;
  this makes the collision impossible rather than unlikely.
- **Per-sleeve budgets:** both strategies share one buying-power pool. Each
  sizes against its sleeve's allocation percentage of the account — neither
  ever reads `self.cash` as "mine." Champions needs this convention too; build
  it before the second strategy exists.
- **Attribution:** ownership per name is unambiguous, so per-sleeve P&L is
  computed from our own trade ledger even though the broker sees one blended
  account.

## Bottom line

Pencil in 80/20 now, define it in exposure terms, build the L/S sleeve to run
market-neutral in its own account, and pre-commit to the scale-up rule — e.g.
"after 2 quarters live, if standalone Sharpe is positive and correlation to
the long book is under 0.3, step to 70/30, target 60/40." That turns the
allocation from a one-time guess into a process.
