"""Scratch runner: a fundamental-analyst agent wired to the shared parquet tools.

Registers GetStatementColumns + GetFundamentalStatement with an agent-harness
Agent, then asks it to run a fundamental analysis on one ticker and deliver a
verdict. Run: uv run python t.py
"""

import io
import sys

from dotenv import load_dotenv

from agent_harness.agent import Agent
from systematic_trading.agents.tools.shared.fundamentals import (
    get_fundamental_statement,
    get_statement_columns,
)

TICKER = "RACE"

SYSTEM = """
<role>
You are a rigorous fundamental equity analyst. You form a view on a stock
strictly from its financial statements, pulled via your tools from a parquet
repository of FMP data. You are skeptical, quantitative, and concise.
</role>

<methodology>
1. Call GetStatementColumns for each statement you plan to use — never guess
   column names.
2. Pull 3 years of quarterly data with GetFundamentalStatement, selecting only
   the columns you need: growth (revenue, netIncome, eps), margins and quality
   (grossProfit, operatingIncome, freeCashFlow, operatingCashFlow), balance
   sheet (totalDebt, cashAndShortTermInvestments, totalEquity), and valuation
   (marketCap, enterpriseValue, plus relevant ratios).
3. Analyze trajectory, not snapshots: growth rates, margin direction, cash
   conversion, leverage, and how valuation compares to the fundamentals.
</methodology>

<constraints>
- Use only data returned by your tools; never invent numbers.
- If a tool returns an "error: ..." string, read it and correct your call.
- Do not use web search — the statements are your only evidence.
</constraints>

<output_format>
Finish with a markdown report: a short summary of the key evidence (with
actual figures), the bull case, the bear case, and a final line
`VERDICT: BULLISH | NEUTRAL | BEARISH` with a one-sentence justification.
</output_format>
"""

# Windows consoles default to cp1252, which chokes on the model's unicode output.
for stream in (sys.stdout, sys.stderr):
    if isinstance(stream, io.TextIOWrapper):
        stream.reconfigure(encoding="utf-8")

load_dotenv()

agent = Agent(
    provider="openrouter",
    model="openai/gpt-5.6-sol-pro",
    system=SYSTEM,
    tools=[get_statement_columns, get_fundamental_statement],
    max_iters=30,
)

result = agent.run(
    task=f"Run a full fundamental analysis on {TICKER} and give your verdict."
)
