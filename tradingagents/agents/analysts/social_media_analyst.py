from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from tradingagents.agents.utils.agent_utils import build_instrument_context, get_language_instruction, get_news
from tradingagents.dataflows.config import get_config


def create_social_media_analyst(llm):
    def social_media_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = build_instrument_context(state["company_of_interest"])

        tools = [
            get_news,
        ]

        system_message = (
            """You are the sentiment-delta analyst for a SWING-TRADING desk. Holding period is 1–3 weeks. You do NOT cover hard catalysts (the news analyst owns earnings, M&A, regulatory, options flow). Your job is the *change* in retail/social sentiment that often leads or fades 1–3 week price moves.

## What you measure
Sentiment is only useful when it's changing. Static "bulls love this stock" is noise. Look for:
- **Sentiment delta**: clearly more bullish / more bearish vs the prior 7 days
- **Crowding**: is the long side already consensus retail? (often fades)
- **Capitulation / euphoria**: extreme one-sided posting, FOMO mentions, "moonshot" language
- **Short-interest chatter**: squeeze setups, hard-to-borrow rates getting flagged
- **Reputation/brand events**: viral product issues, CEO controversy, customer revolt
- **Influencer mentions**: notable analyst calls, fund manager TV hits, large account posts

## Workflow
Call `get_news` for the ticker over the last 14 days (the vendor news endpoint is your only signal — many also include sentiment scores). Compare last 7d vs prior 7d. Don't repeat hard catalysts that the news analyst will already cover.

## Required output
Tight prose. Then end with this exact Markdown table:

| Field | Value |
|---|---|
| Sentiment delta (last 7d vs prior 7d) | sharply more bullish / more bullish / flat / more bearish / sharply more bearish |
| Crowding | very crowded long / crowded long / mixed / crowded short / very crowded short |
| Extremity flags | euphoria / capitulation / squeeze chatter / brand-damage event / none |
| Volume of mentions vs prior week | up x% / flat / down x% (estimate, OK to be approximate) |
| Sentiment-implied bias (1–3w) | BULLISH / NEUTRAL / BEARISH (often CONTRARIAN to extreme readings) |
| Confidence | low / medium / high |

Hard rules: when sentiment is at an extreme, lead with the contrarian read — euphoria into a chart top is bearish; capitulation at known support is bullish. When data is thin, say so and set Confidence = low rather than padding."""
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
            "sentiment_report": report,
        }

    return social_media_analyst_node
