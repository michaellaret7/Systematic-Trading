"""Screeners: thin opinion layers over the shared fundamentals panel.

Each screener is one module exposing a single public ``screen(as_of=None)``
entry point — a criteria dict, score weights, and nothing else. New screener =
new file here; new fact = new metric column in ``fundamentals/metrics``.
"""
