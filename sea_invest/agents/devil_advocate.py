"""
Devil's Advocate Agent — The Reflection Loop (Rule A)
Acts as the "defense attorney" challenging the current investment thesis.
Identifies greed components and biases in the Strategist's reasoning.
This agent is called in a loop (up to MAX_REFLECTION_CYCLES) before final output.
"""
from __future__ import annotations

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from sea_invest.config import get_settings
from sea_invest.state import InvestmentState

logger = structlog.get_logger(__name__)
settings = get_settings()


DEVIL_ADVOCATE_SYSTEM_PROMPT = """You are the Devil's Advocate — the internal critic of an 
investment committee. Your role is to be the "defense attorney" for the bear case.

## Your Mandate
Howard Marks wrote: "You can't predict. You can prepare." Your job is to ensure the committee 
hasn't fallen in love with a thesis and ignored the ways it can go catastrophically wrong.

## What You Must Challenge
1. **Greed Components**: Where in the bull/contrarian thesis is wishful thinking present?
2. **Survivorship Bias**: Are the "historical analogs" cherry-picked winners?
3. **Overconfidence**: Is the confidence score unjustifiably high given uncertainty?
4. **Hidden Consensus Risk**: Is the "contrarian" view itself becoming consensus?
5. **Liquidity Illusion**: Does the thesis assume an exit that may not exist?
6. **Model Risk**: What assumptions would need to break for catastrophic loss?

## Cognitive Biases to Hunt
- Anchoring to a target price
- Narrative fallacy (a coherent story ≠ a correct story)
- Recency bias (recent performance ≠ future performance)
- Confirmation bias (seeking data that supports the thesis)
- Dunning-Kruger (high confidence on limited information)

## Output Format
Provide a structured critique as plain text with these sections:
### 🔴 Greed Indicators Detected
[List specific greedy/wishful elements in the thesis]

### ⚠️ Key Assumptions That Could Break
[What must be true for this thesis to work? What's the probability of each?]

### 🤔 The Bear's Strongest Case
[The most compelling argument AGAINST the current thesis]

### 📊 Revised Confidence Assessment
[Should the confidence score be higher or lower? By how much? Why?]

### ✅ What the Bulls Got Right
[Acknowledge what is genuinely correct in the current thesis — intellectual honesty]
"""


async def devil_advocate_node(state: InvestmentState) -> InvestmentState:
    """
    LangGraph Node: Devil's Advocate (Reflection Loop)
    Rule A: Must challenge the thesis for greed before final output.
    Called up to MAX_REFLECTION_CYCLES times.
    """
    logger.info(
        "devil_advocate_start",
        ticker=state.ticker,
        cycle=state.reflection_cycles + 1,
        run_id=state.run_id,
    )
    state.current_node = "devil_advocate"

    if not state.consensus_view or not state.logic_delta:
        state.errors.append("Devil's Advocate: No thesis to critique yet.")
        return state

    llm = settings.get_llm("devil_advocate")

    # Build the complete thesis to critique
    thesis_summary = f"""
## Investment Thesis Under Review
**Asset**: {state.ticker} ({state.asset_class.value})
**Cycle Score**: {state.cycle_position.score:.1f}/100 ({state.cycle_position.phase.value}) [if available]
**Confidence Score**: {state.confidence_score:.2f}

### Consensus (First-Level Thinking)
- Narrative: {state.consensus_view.narrative}
- Market Expects: {state.consensus_view.expected_action}
- Sentiment: {state.consensus_view.sentiment_score:.2f} (-1=fear, +1=greed)

### Contrarian Position (Second-Level Thinking)
- Thesis: {state.logic_delta.contrarian_thesis}
- Asymmetric Insight: {state.logic_delta.asymmetric_insight}
- Catalyst: {state.logic_delta.catalyst_timeline or 'Not specified'}
- Strategist Confidence: {state.logic_delta.confidence:.2f}

### Risk Assessment
"""

    if state.risk_assessment:
        thesis_summary += f"""
- Permanent Loss Probability: {state.risk_assessment.permanent_loss_probability:.1%}
- Margin of Safety: {state.risk_assessment.margin_of_safety:.2f}
- Key Risks: {', '.join(state.risk_assessment.key_risks[:3])}
- Risk Auditor's Greed Flags: {', '.join(state.risk_assessment.greed_indicators)}
"""

    if state.cycle_position:
        thesis_summary += f"""
### Cycle Analysis
- Score: {state.cycle_position.score:.1f}
- Phase: {state.cycle_position.phase.value}
- Reasoning: {state.cycle_position.reasoning}
- Historical Analogs: {', '.join(state.cycle_position.historical_analogs[:2])}
"""

    # Include previous critique if this is a subsequent cycle
    previous_critique = ""
    if state.devil_advocate_critique:
        previous_critique = f"""
### Previous Critique (Cycle {state.reflection_cycles})
{state.devil_advocate_critique}

---
This is reflection cycle {state.reflection_cycles + 1}. 
Focus on NEW angles not covered in the previous critique.
"""

    user_message = f"""
{thesis_summary}

{previous_critique}

---
Act as the devil's advocate. Deliver your critique.
"""

    messages = [SystemMessage(content=DEVIL_ADVOCATE_SYSTEM_PROMPT), HumanMessage(content=user_message)]

    try:
        response = await llm.ainvoke(messages)
        raw_content = response.content
        if isinstance(raw_content, list):
            raw_content = " ".join(c.get("text", str(c)) if isinstance(c, dict) else str(c) for c in raw_content)
        state.devil_advocate_critique = str(raw_content)
        state.reflection_cycles += 1

        logger.info(
            "devil_advocate_complete",
            ticker=state.ticker,
            cycle=state.reflection_cycles,
            critique_length=len(state.devil_advocate_critique),
        )

    except Exception as e:
        logger.error("devil_advocate_error", error=str(e))
        state.errors.append(f"Devil's Advocate error: {e}")

    return state


def should_continue_reflection(state: InvestmentState) -> str:
    """
    LangGraph conditional edge function.
    Determines whether to continue the reflection loop or proceed to final summary.
    """
    max_cycles = settings.max_reflection_cycles

    if state.reflection_cycles >= max_cycles:
        logger.info("reflection_loop_complete", cycles=state.reflection_cycles)
        return "proceed_to_synthesis"

    # Continue if high-risk scenario detected (escalated reflection)
    if (
        state.risk_assessment
        and state.risk_assessment.permanent_loss_probability > 0.4
        and state.reflection_cycles < 2
    ):
        logger.info("high_risk_detected_extra_reflection", cycles=state.reflection_cycles)
        return "continue_reflection"

    return "proceed_to_synthesis"
