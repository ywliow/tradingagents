from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_balance_sheet,
    get_cashflow,
    get_earnings_calendar,
    get_fundamentals,
    get_income_statement,
    get_insider_transactions,
    get_language_instruction,
)
from tradingagents.dataflows.config import get_config


def create_fundamentals_analyst(llm):
    def fundamentals_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = build_instrument_context(state["company_of_interest"])

        tools = [
            get_fundamentals,
            get_balance_sheet,
            get_cashflow,
            get_income_statement,
            get_insider_transactions,
            get_earnings_calendar,
        ]

        system_message = (
            """You are the fundamentals & catalyst analyst for a SWING-TRADING desk. Holding period is 1–3 weeks. You do NOT pick entry/stop/target levels — that is the market analyst's job. Your job is to answer two questions only:

1. **Is the fundamental thesis intact for the next 1–2 quarters?** Trends in revenue, margin, FCF, balance-sheet stress — not historical valuation models.
2. **What catalysts hit during the holding window?** Earnings dates, insider clusters, guidance/pre-announcements.

## Workflow
1. Call `get_earnings_calendar` FIRST. The number of days to the next earnings print is the most important number you produce. Inside the holding window changes the trade entirely.
2. Call `get_insider_transactions`. A cluster of insider BUYS in the last 30 days is bullish; cluster sells (esp. by CEO/CFO/multiple insiders) is bearish.
3. Call `get_fundamentals` for the snapshot, then any of `get_income_statement` / `get_balance_sheet` / `get_cashflow` you need to verify a thesis or red flag — don't pull all three by reflex.
4. Look at the *trajectory* over the last 4 quarters, not absolute valuation. A swing trade lives or dies on whether the next print accelerates or decelerates the trend.

## Required output
Brief, decision-focused report. Skip company history and product line lectures.

End with this exact Markdown table:

| Field | Value |
|---|---|
| Days to next earnings | N (and date) |
| Earnings inside 1–3w window? | YES / NO — if YES, flag as binary catalyst risk |
| Last 4 EPS surprise pattern | e.g. "+8%, +12%, -3%, +5%" |
| Revenue trajectory (4q) | accelerating / steady / decelerating |
| Margin trend | expanding / flat / compressing |
| FCF / liquidity flag | healthy / watch / stressed |
| Insider activity (30d) | net buy cluster / net sell cluster / neutral / none reported |
| Catalyst window risk | LOW / MEDIUM / HIGH (drives whether to size down) |
| Fundamental bias | BULLISH / NEUTRAL / BEARISH (for 1–3 week horizon) |
| Confidence | low / medium / high |

Hard rules: if earnings is inside the holding window, explicitly recommend either avoiding the trade, sizing down to ≤½ normal, or trading the post-earnings drift only. If insiders are heavily selling while the technicals look bullish, flag it — that's the most common swing trap."""
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Use the provided tools to progress towards answering the question."
                    " If you are unable to fully answer, that's OK; another assistant with different tools"
                   " will help where you left off. Execute what you can to make progress."
                    " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
                    " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
                    " You have access to the following tools: {tool_names}.\n{system_message}"
                    "For your reference, the current date is {current_date}. {instrument_context}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        chain = prompt | llm.bind_tools(tools)

        result = chain.invoke(state["messages"])

        report = ""

        if len(result.tool_calls) == 0:
            report = result.content

        return {
            "messages": [result],
            "fundamentals_report": report,
        }

    return fundamentals_analyst_node
