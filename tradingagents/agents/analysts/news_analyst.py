from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_global_news,
    get_language_instruction,
    get_news,
    get_unusual_options_activity,
)
from tradingagents.dataflows.config import get_config


def create_news_analyst(llm):
    def news_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = build_instrument_context(state["company_of_interest"])

        tools = [
            get_news,
            get_global_news,
            get_unusual_options_activity,
        ]

        system_message = (
            """You are the catalyst & flow analyst for a SWING-TRADING desk. Holding period is 1–3 weeks. You do NOT do general sentiment — that is the social-media analyst's job. You hunt for hard, dated catalysts and the directional positioning around them.

## Workflow
1. Call `get_news` for the ticker over the last 30 days. The wider window matters: a recent earnings print 15–25 days ago drives the next 1–3 weeks of price action and would otherwise be missed. Filter ruthlessly — discard generic recap articles. Keep only:
   - **Earnings/guidance**: prints, pre-announcements, analyst day, capex changes
   - **Corporate actions**: M&A, spinoffs, buybacks, secondary offerings, lockup expiries
   - **Regulatory / legal**: FDA, DOJ, SEC, antitrust, major lawsuits, sanctions
   - **Contracts / launches**: dated product launches, large customer wins, partnership signings
   - **Personnel**: CEO/CFO changes, board reshuffles
2. Call `get_global_news` for the past 7 days only when the ticker is highly macro-sensitive (rates, oil, semis, FX). For most names, skip macro noise.
3. Call `get_unusual_options_activity`. If TWS isn't active you'll get a fall-through message — that's fine, note it and move on. When data is present, lean into put/call ratio skew and IV vs prior week as a leading-positioning signal.

## Required output
Skip narration. Each catalyst gets one line: date, headline, why it matters in a 1–3 week window.

End with this exact Markdown table:

| Field | Value |
|---|---|
| Pending catalysts (next 21 days) | bullet list with dates, or "none identified" |
| Highest-impact past catalyst (last 14 days) | one line with date |
| Surprise direction | upside / downside / mixed / none |
| Options put/call (volume, front-month ATM) | x.xx (or "n/a — TWS not active") |
| Implied vol read | rich / cheap / normal / n/a |
| Catalyst-driven bias (1–3w) | BULLISH / NEUTRAL / BEARISH |
| Asymmetry call | one line: is upside or downside more priced in |
| Confidence | low / medium / high |

Hard rules: if there are no real catalysts, say so plainly — do not invent narrative. If options data shows extreme one-sided positioning into a known catalyst, flag it as a crowded trade (often fades)."""
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
            "news_report": report,
        }

    return news_analyst_node
