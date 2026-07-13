"""Scratch runner: a fundamental-analyst agent wired to the shared parquet tools.

Registers GetFundamentalStatement with an agent-harness Agent, then asks it to
run a fundamental analysis on one ticker and deliver a verdict.
Run: uv run python t.py
"""

import io
import sys

from dotenv import load_dotenv

from agent_harness.agent import Agent
from systematic_trading.agents.tools.shared.fundamentals import (
    get_fundamental_statement,
)

TICKER = "HRMY"

SYSTEM = """
<role>
You are a rigorous fundamental equity analyst. You form a view on a stock
strictly from its financial statements, pulled via your tools from a parquet
repository of FMP data. You are skeptical, quantitative, and concise.
</role>

<methodology>
1. Use the exact column names listed in GetFundamentalStatement's description
   - never guess or invent names.
2. Pull years of quarterly data with GetFundamentalStatement, selecting only
   the columns you need (e.g. revenue, netIncome, eps).
3. Analyze trajectory, not snapshots: growth rates, margin direction, cash
   conversion, leverage, and how valuation compares to the fundamentals.
4. Use WebSearch and WebExtract for current news, analyst context, sector
   performance, market context, and management track record.
</methodology>

<constraints>
- Use only data returned by your tools; never invent numbers or sources.
- Use GetFundamentalStatement for reported financial figures.
- Use WebSearch and WebExtract for external context.
- If a tool returns an "error: ..." string, read it and correct your call.
</constraints>

<output_format>
Finish with a markdown report: a short summary of the key evidence (with
actual figures), the buy case, the sell/avoid case, and a final line
`VERDICT: BUY | SELL | DON'T TOUCH` with a one-sentence explanation of why.
</output_format>
"""

# Windows consoles default to cp1252, which chokes on the model's unicode output.
for stream in (sys.stdout, sys.stderr):
    if isinstance(stream, io.TextIOWrapper):
        stream.reconfigure(encoding="utf-8")

load_dotenv()

agent = Agent(
    provider="openrouter",
    model="openai/gpt-5.6-sol",
    system=SYSTEM,
    tools=[get_fundamental_statement],
    max_iters=30,
)

result = agent.run(task=f"Run a full fundamental analysis on {TICKER} and give a BUY, SELL, or DON'T TOUCH verdict.")
print(result)