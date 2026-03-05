"""
Strategist Agent — "Second-Level Thinker"
The core contrarian reasoning engine based on Howard Marks' second-level thinking.
Challenges consensus narratives and identifies mispriced assets.
"""
from __future__ import annotations

import json

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser

from sea_invest.config import get_settings
from sea_invest.state import (
    AssetClass,
    ConsensusView,
    CyclePhase,
    CyclePosition,
    InvestmentState,
    LogicDelta,
)

logger = structlog.get_logger(__name__)
settings = get_settings()


# ─────────────────────────────────────────────
# Prompts (versioned, evolvable by Oracle)
# ─────────────────────────────────────────────

STRATEGIST_SYSTEM_PROMPT_V1 = """You are a Howard Marks-style second-level thinker and contrarian investor.

## Your Core Philosophy
"First-level thinking says, 'It's a good company; let's buy the stock.' Second-level thinking 
says, 'It's a good company, but everyone knows it's good, so it's not cheap. Let's sell.'"

## Your Analytical Framework

### Step 1: Identify the Consensus (First-Level View)
- What does the market currently believe about this asset?  
- What is the dominant narrative? What action does the consensus expect?
- What is the prevailing sentiment (fearful/neutral/greedy)?

### Step 2: Challenge the Consensus (Second-Level View)
- Why might the consensus be WRONG? What are they missing or ignoring?
- Are market participants being swayed by recency bias, herd mentality, or narrative fallacy?
- What asymmetric information or insight do you have that challenges the consensus?

### Step 3: Locate on the Pendulum (Market Cycle Position)
Score the current cycle position from 0 to 100:
- 0-15: Deep Fear / Peak Pessimism (maximum opportunity per Marks)
- 15-35: General Pessimism
- 35-65: Neutral / Transitional  
- 65-85: Optimism / Complacency
- 85-100: Euphoria / Peak Greed (maximum danger per Marks)

Key cycle signals:
- Credit availability and covenant quality
- New issue volume and deal quality
- Investor risk appetite and leverage levels
- Valuation multiples vs historical norms
- "This time is different" syndrome prevalence

## RAG Context from Howard Marks (inject from knowledge base)
{rag_context}

## Output Format
Return a valid JSON object with this exact structure:
{{
  "consensus_view": {{
    "narrative": "string - the dominant first-level story",
    "expected_action": "string - what consensus expects",
    "sentiment_score": float between -1.0 (fear) and 1.0 (greed),
    "supporting_evidence": ["evidence1", "evidence2"]
  }},
  "logic_delta": {{
    "contrarian_thesis": "string - why consensus is wrong",
    "asymmetric_insight": "string - what market is missing",
    "catalyst_timeline": "string - when/how mispricing corrects",
    "confidence": float between 0.0 and 1.0
  }},
  "cycle_position": {{
    "score": float between 0 and 100,
    "phase": "one of: deep_fear, pessimism, neutral, optimism, euphoria",
    "reasoning": "string - detailed cycle reasoning",
    "historical_analogs": ["analog1", "analog2"]
  }},
  "confidence_score": float between 0.0 and 1.0
}}
"""


def _get_strategist_prompt(version: str = "v1") -> str:
    """Retrieve versioned prompt. Oracle can inject evolved versions."""
    # In production, this reads from DB via PromptVersion table
    prompts = {
        "v1": STRATEGIST_SYSTEM_PROMPT_V1,
    }
    return prompts.get(version, STRATEGIST_SYSTEM_PROMPT_V1)


# ─────────────────────────────────────────────
# Main Strategist Node
# ─────────────────────────────────────────────

async def strategist_node(state: InvestmentState) -> InvestmentState:
    """
    LangGraph Node: Strategist (Second-Level Thinker)
    Uses Howard Marks' contrarian framework to challenge consensus and position on the cycle.
    """
    logger.info("strategist_start", ticker=state.ticker, run_id=state.run_id)
    state.current_node = "strategist"

    if not state.market_data:
        state.errors.append("Strategist: No market data available. Ingestor must run first.")
        return state

    llm = settings.get_llm("strategist")
    system_prompt = _get_strategist_prompt().format(rag_context=state.rag_context or "No RAG context available.")

    user_message = f"""
## Asset Under Analysis
**Ticker:** {state.ticker}  
**Asset Class:** {state.asset_class.value}
**Current Date:** {state.created_at.strftime('%Y-%m-%d')}

## Market Data Digest
{state.market_data.earnings_summary}

## Macro Indicators
{json.dumps(state.market_data.macro_indicators, indent=2)}

---
Apply your second-level thinking framework. Return ONLY the JSON output.
"""

    messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_message)]

    try:
        response = await llm.ainvoke(messages)
        raw_content = response.content
        if isinstance(raw_content, list):
            raw_content = " ".join(c.get("text", str(c)) if isinstance(c, dict) else str(c) for c in raw_content)
        raw_content = str(raw_content).strip()

        # Strip markdown code blocks if present
        if "```json" in raw_content:
            raw_content = raw_content.split("```json")[1].split("```")[0].strip()
        elif "```" in raw_content:
            raw_content = raw_content.split("```")[1].split("```")[0].strip()

        data = json.loads(raw_content)

        # Populate consensus view
        cv = data.get("consensus_view", {})
        state.consensus_view = ConsensusView(
            narrative=cv.get("narrative", ""),
            expected_action=cv.get("expected_action", ""),
            sentiment_score=float(cv.get("sentiment_score", 0.0)),
            supporting_evidence=cv.get("supporting_evidence", []),
        )

        # Populate logic delta
        ld = data.get("logic_delta", {})
        state.logic_delta = LogicDelta(
            contrarian_thesis=ld.get("contrarian_thesis", ""),
            asymmetric_insight=ld.get("asymmetric_insight", ""),
            catalyst_timeline=ld.get("catalyst_timeline"),
            confidence=float(ld.get("confidence", 0.5)),
        )

        # Populate cycle position
        cp = data.get("cycle_position", {})
        phase_str = cp.get("phase", "neutral")
        state.cycle_position = CyclePosition(
            score=float(cp.get("score", 50.0)),
            phase=CyclePhase(phase_str),
            reasoning=cp.get("reasoning", ""),
            historical_analogs=cp.get("historical_analogs", []),
        )

        state.confidence_score = float(data.get("confidence_score", 0.5))
        logger.info(
            "strategist_complete",
            ticker=state.ticker,
            cycle_score=state.cycle_position.score,
            phase=state.cycle_position.phase.value,
        )

    except json.JSONDecodeError as e:
        error_msg = f"Strategist JSON parse error: {e}. Raw: {raw_content[:500]}"
        logger.error("strategist_parse_error", error=error_msg)
        state.errors.append(error_msg)
    except Exception as e:
        logger.error("strategist_error", error=str(e))
        state.errors.append(f"Strategist error: {e}")

    return state
