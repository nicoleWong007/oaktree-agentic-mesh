"""
Risk Auditor Agent
Evaluates probability of permanent capital loss using Howard Marks' risk framework.
Identifies greed signals and calculates margin of safety.
"""
from __future__ import annotations

import json

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from sea_invest.config import get_settings
from sea_invest.state import InvestmentState, RiskAssessment

logger = structlog.get_logger(__name__)
settings = get_settings()


RISK_AUDITOR_SYSTEM_PROMPT = """You are a Risk Auditor specializing in Howard Marks' approach to 
risk management. Your singular focus: identifying the probability of PERMANENT CAPITAL LOSS.

## Howard Marks' Risk Principles

"The most important thing is not maximizing return; it's avoiding permanent loss."
"Risk means more things can happen than will happen."
"Oaktree's investment philosophy rests on the belief that superior long-term results are best 
achieved by combining excellent asset selection with thoughtful risk management."

## Risk Categories to Evaluate

### 1. Permanent Capital Loss Drivers
- Business model obsolescence or competitive destruction
- Financial distress from leverage / covenant breach
- Fraud, governance failure, or accounting chicanery  
- Regulatory or legal existential threats
- Currency / sovereign risk (for international assets)

### 2. Greed Signals (Marks' Warning Signs)
- Narrative-driven buying ("this sector always goes up")
- New paradigm justifications for elevated valuations
- Aggressive covenant stripping in credit
- Excessive leverage to amplify returns
- "Fear of missing out" driving flows rather than fundamentals
- Declining risk premiums despite rising uncertainty

### 3. Margin of Safety Analysis
Calculate the buffer between current price and intrinsic value:
- > 0.3: Deep value, wide margin of safety
- 0.1 to 0.3: Moderate safety margin
- -0.1 to 0.1: Fair value, thin margin
- < -0.1: Overvalued, negative margin of safety

## RAG Knowledge Base Context
{rag_context}

## Output Format (JSON only, no markdown)
{{
  "permanent_loss_probability": float 0.0 to 1.0,
  "downside_scenarios": [
    "Scenario 1: [name] — [mechanism] — [probability] — [expected drawdown]",
    "Scenario 2: ..."
  ],
  "margin_of_safety": float -1.0 to 1.0,
  "key_risks": ["Risk 1", "Risk 2", "Risk 3"],
  "greed_indicators": ["Any signs of excess greed or complacency"],
  "risk_narrative": "paragraph explaining the overall risk posture"
}}
"""


async def risk_auditor_node(state: InvestmentState) -> InvestmentState:
    """
    LangGraph Node: Risk Auditor
    Evaluates downside scenarios and permanent capital loss probability.
    Critically, it flags GREED indicators to feed into the Reflection Loop.
    """
    logger.info("risk_auditor_start", ticker=state.ticker, run_id=state.run_id)
    state.current_node = "risk_auditor"

    if not state.market_data or not state.consensus_view:
        state.errors.append("Risk Auditor: Missing market data or consensus view.")
        return state

    llm = settings.get_llm("risk_auditor")
    system_prompt = RISK_AUDITOR_SYSTEM_PROMPT.format(
        rag_context=state.rag_context or "No RAG context available."
    )

    consensus_summary = (
        f"Consensus Narrative: {state.consensus_view.narrative}\n"
        f"Consensus Expected Action: {state.consensus_view.expected_action}\n"
        f"Sentiment Score: {state.consensus_view.sentiment_score:.2f}"
    )

    logic_delta_summary = ""
    if state.logic_delta:
        logic_delta_summary = (
            f"Contrarian Thesis: {state.logic_delta.contrarian_thesis}\n"
            f"Asymmetric Insight: {state.logic_delta.asymmetric_insight}\n"
            f"Strategist Confidence: {state.logic_delta.confidence:.2f}"
        )

    cycle_summary = ""
    if state.cycle_position:
        cycle_summary = (
            f"Cycle Score: {state.cycle_position.score:.1f}/100\n"
            f"Cycle Phase: {state.cycle_position.phase.value}\n"
            f"Cycle Reasoning: {state.cycle_position.reasoning}"
        )

    user_message = f"""
## Asset: {state.ticker} ({state.asset_class.value})

## Market Data
{state.market_data.earnings_summary}

## Macro Environment
{json.dumps(state.market_data.macro_indicators, indent=2)}

## Strategist's Analysis
{consensus_summary}

{logic_delta_summary}

## Cycle Position
{cycle_summary}

---
Audit this investment for permanent capital loss risk. Return ONLY the JSON output.
"""

    messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_message)]

    try:
        response = await llm.ainvoke(messages)
        raw_content = response.content
        if isinstance(raw_content, list):
            raw_content = " ".join(c.get("text", str(c)) if isinstance(c, dict) else str(c) for c in raw_content)
        raw_content = str(raw_content).strip()

        if "```json" in raw_content:
            raw_content = raw_content.split("```json")[1].split("```")[0].strip()
        elif "```" in raw_content:
            raw_content = raw_content.split("```")[1].split("```")[0].strip()

        data = json.loads(raw_content)

        state.risk_assessment = RiskAssessment(
            permanent_loss_probability=float(data.get("permanent_loss_probability", 0.3)),
            downside_scenarios=data.get("downside_scenarios", []),
            margin_of_safety=float(data.get("margin_of_safety", 0.0)),
            key_risks=data.get("key_risks", []),
            greed_indicators=data.get("greed_indicators", []),
        )

        logger.info(
            "risk_auditor_complete",
            ticker=state.ticker,
            permanent_loss_prob=state.risk_assessment.permanent_loss_probability,
            margin_of_safety=state.risk_assessment.margin_of_safety,
        )

    except json.JSONDecodeError as e:
        state.errors.append(f"Risk Auditor JSON parse error: {e}")
    except Exception as e:
        logger.error("risk_auditor_error", error=str(e))
        state.errors.append(f"Risk Auditor error: {e}")

    return state
