"""Reusable stock screeners shared by strategies.

A screener package holds opinions only (criteria, score weights, preview columns)
and exposes ``screen()``; panels under ``panels/`` own the data and metrics;
``shared/`` owns the panel-agnostic machinery. Register new screeners here so the
panel build previews them and future tooling can enumerate them.
"""

from systematic_trading.screeners import csf_champions, junk_shorts

SCREENERS = {
    "csf_champions": csf_champions,
    "junk_shorts": junk_shorts,
}
