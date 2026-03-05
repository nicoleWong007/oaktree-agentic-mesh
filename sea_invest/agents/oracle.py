"""
Oracle Agent — The Evolution Engine (Rule C)
The self-evolving core of SEA-Invest.

Mechanism:
1. After each analysis run, the Oracle records predictions to the database.
2. When actual market outcomes are known, the Oracle computes prediction diffs.
3. If 3+ consecutive cycle-positioning errors occur for an asset class,
   the Oracle generates an improved System Prompt for the Strategist and
   tests it against historical data in the Shadow System.
"""
from __future__ import annotations

import difflib
import json
import textwrap
import uuid
from datetime import datetime, timedelta
from typing import Optional

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from sea_invest.config import get_settings
from sea_invest.state import (
    AssetClass,
    EvolutionLogEntry,
    InvestmentState,
    PromptVersion,
    RecommendationAction,
)

logger = structlog.get_logger(__name__)
settings = get_settings()


# ─────────────────────────────────────────────
# Prediction vs Reality Diff Engine
# ─────────────────────────────────────────────

class PredictionDiff:
    """
    Computes the structured diff between what the Strategist predicted
    and what actually happened in the market.
    """

    def __init__(
        self,
        predicted_cycle_score: float,
        actual_cycle_score: float,
        predicted_action: RecommendationAction,
        actual_return_pct: float,
        asset_class: AssetClass,
    ):
        self.predicted_cycle_score = predicted_cycle_score
        self.actual_cycle_score = actual_cycle_score
        self.cycle_error = actual_cycle_score - predicted_cycle_score
        self.predicted_action = predicted_action
        self.actual_return_pct = actual_return_pct
        self.asset_class = asset_class

        # Was the cycle direction correct?
        self.direction_correct = (
            (predicted_cycle_score < 50 and actual_return_pct > 0) or
            (predicted_cycle_score > 50 and actual_return_pct < 0)
        )

    @property
    def cycle_error_magnitude(self) -> float:
        return abs(self.cycle_error)

    @property
    def is_significant_error(self) -> bool:
        """Error > 15 points on 0-100 scale is considered significant."""
        return self.cycle_error_magnitude > 15.0

    def to_narrative(self) -> str:
        """Generate human-readable diff narrative for Oracle reasoning."""
        direction = "↑ bullish" if self.cycle_error > 0 else "↓ bearish"
        correctness = "✅ CORRECT direction" if self.direction_correct else "❌ WRONG direction"

        return textwrap.dedent(f"""
        ## Prediction vs Reality Analysis
        
        **Cycle Score Predicted**: {self.predicted_cycle_score:.1f}/100
        **Cycle Score Actual**: {self.actual_cycle_score:.1f}/100
        **Error**: {self.cycle_error:+.1f} (actual was {direction} than predicted)
        **Magnitude**: {'Significant' if self.is_significant_error else 'Minor'} error
        
        **Action Predicted**: {self.predicted_action.value}
        **Actual Return**: {self.actual_return_pct:+.2f}%
        **Direction**: {correctness}
        """).strip()


# ─────────────────────────────────────────────
# Prompt Evolution Engine
# ─────────────────────────────────────────────

ORACLE_EVOLUTION_PROMPT = """You are the Oracle — the meta-learning engine of a self-improving 
investment system. Your role is to evolve the Strategist Agent's System Prompt based on 
observed prediction errors.

## Your Mission
Study the pattern of prediction errors and generate an IMPROVED System Prompt that would 
have made better predictions. You are literally rewriting the AI's instructions.

## Analysis Framework

### Step 1: Error Pattern Recognition
Identify WHY the predictions were wrong:
- Was the cycle score systematically too optimistic (bullish bias)?
- Was it too pessimistic (bearish bias)?
- Were specific macro factors ignored?
- Were greed/fear signals misinterpreted?
- Were historical analogs poorly selected?
- Was the confidence too high or too low?

### Step 2: Root Cause Attribution
Attribute each error to a specific component:
- Macro interpretation failure
- Valuation framework weakness
- Sentiment misreading
- Sector-specific blind spot
- Timing error (right thesis, wrong timeline)

### Step 3: Prompt Surgery
Generate specific modifications to the prompt:
- ADD new instructions for the identified blind spots
- REMOVE or MODIFY instructions that led to systematic bias
- INJECT new heuristics for the specific asset class
- CALIBRATE confidence scoring guidelines

## Output Format (JSON)
{{
  "error_pattern_analysis": "string - identify the systematic error pattern",
  "root_causes": ["cause1", "cause2"],
  "prompt_modifications": [
    {{
      "type": "ADD | MODIFY | REMOVE",
      "section": "which section of the prompt",
      "original": "the original text (if MODIFY/REMOVE)",
      "replacement": "the new instruction text",
      "rationale": "why this change addresses the error"
    }}
  ],
  "new_system_prompt": "the complete, revised system prompt",
  "expected_improvement": "how this should improve future predictions",
  "confidence_in_improvement": float 0.0 to 1.0
}}
"""


async def generate_evolved_prompt(
    current_prompt: str,
    error_history: list[PredictionDiff],
    asset_class: AssetClass,
    llm,
) -> Optional[dict]:
    """Core Oracle logic: generate an evolved prompt based on error history."""

    error_narratives = "\n\n".join([f"Error {i+1}:\n{e.to_narrative()}" for i, e in enumerate(error_history)])

    user_message = f"""
## Asset Class Under Review: {asset_class.value}

## Current Strategist System Prompt (to be evolved):
```
{current_prompt}
```

## Consecutive Prediction Errors ({len(error_history)} errors):
{error_narratives}

## Pattern Summary:
- Average Cycle Score Error: {sum(e.cycle_error for e in error_history)/len(error_history):+.1f}
- Direction Correct Rate: {sum(1 for e in error_history if e.direction_correct)/len(error_history):.0%}
- Mean Absolute Error: {sum(e.cycle_error_magnitude for e in error_history)/len(error_history):.1f}

---
Analyze the error pattern and generate an improved System Prompt. Return ONLY the JSON output.
"""

    messages = [SystemMessage(content=ORACLE_EVOLUTION_PROMPT), HumanMessage(content=user_message)]

    try:
        response = await llm.ainvoke(messages)
        raw = response.content
        if isinstance(raw, list):
            raw = " ".join(c.get("text", str(c)) if isinstance(c, dict) else str(c) for c in raw)
        raw = str(raw).strip()
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()
        return json.loads(raw)
    except Exception as e:
        logger.error("oracle_evolution_failed", error=str(e))
        return None


def compute_prompt_diff(old_prompt: str, new_prompt: str) -> str:
    """Generate a readable unified diff between prompt versions."""
    old_lines = old_prompt.splitlines(keepends=True)
    new_lines = new_prompt.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines, new_lines,
        fromfile="prompt_v_current",
        tofile="prompt_v_evolved",
        lineterm="",
    )
    return "".join(list(diff))


# ─────────────────────────────────────────────
# Shadow System Backtest
# ─────────────────────────────────────────────

async def shadow_backtest(
    evolved_prompt: str,
    historical_states: list[dict],
    llm,
) -> float:
    """
    Rule C: Test the evolved prompt against historical data.
    Returns a performance score (higher = better).
    
    In production: for each historical state, run the Strategist with the
    evolved prompt and compare its cycle prediction to the known outcome.
    
    This is a simplified scoring implementation — extend with real backtesting.
    """
    if not historical_states:
        logger.warning("shadow_backtest_no_history")
        return 0.5  # Neutral score if no history

    scores = []
    for hist in historical_states[-settings.shadow_backtest_days:]:
        predicted = hist.get("predicted_cycle_score", 50.0)
        actual = hist.get("actual_cycle_score", 50.0)
        error = abs(actual - predicted)
        # Score: 1.0 for perfect, 0.0 for max error (100 points)
        scores.append(max(0.0, 1.0 - (error / 100.0)))

    return sum(scores) / len(scores)


# ─────────────────────────────────────────────
# Main Oracle Node
# ─────────────────────────────────────────────

async def oracle_node(state: InvestmentState) -> InvestmentState:
    """
    LangGraph Node: Oracle (Evolution Engine)
    
    Primary role: Record this run's predictions for future evaluation.
    Secondary role: If EVOLUTION_THRESHOLD consecutive errors reached,
                    generate evolved prompt and test in shadow system.
    """
    logger.info("oracle_start", ticker=state.ticker, run_id=state.run_id)
    state.current_node = "oracle"

    # Step 1: Log this prediction to evolution tracking
    if state.cycle_position and state.final_recommendation:
        current_entry = EvolutionLogEntry(
            version_id=str(uuid.uuid4()),
            agent_role="strategist",
            prompt_diff="",  # Populated if/when Oracle evolves the prompt
            predicted_cycle_score=state.cycle_position.score,
            predicted_action=state.final_recommendation,
        )
        state.evolution_log.append(current_entry)

        # Persist to database (delegated to persistence layer)
        logger.info(
            "oracle_prediction_logged",
            run_id=state.run_id,
            cycle_score=state.cycle_position.score,
            recommendation=state.final_recommendation.value,
        )

    # Step 2: Check if evolution is needed
    # (In production: query DB for consecutive_errors by asset_class)
    if state.consecutive_cycle_errors >= settings.evolution_threshold:
        logger.warning(
            "oracle_evolution_triggered",
            errors=state.consecutive_cycle_errors,
            threshold=settings.evolution_threshold,
            asset_class=state.asset_class.value,
        )
        state.oracle_triggered = True
        await _run_evolution_cycle(state)
    else:
        logger.info(
            "oracle_evolution_not_needed",
            consecutive_errors=state.consecutive_cycle_errors,
            threshold=settings.evolution_threshold,
        )

    return state


async def _run_evolution_cycle(state: InvestmentState) -> None:
    """
    Internal method: execute the full prompt evolution and shadow testing cycle.
    """
    from sea_invest.agents.strategist import STRATEGIST_SYSTEM_PROMPT_V1

    llm = settings.get_llm("oracle")

    # Build error history from evolution log
    recent_errors = [
        PredictionDiff(
            predicted_cycle_score=entry.predicted_cycle_score,
            actual_cycle_score=entry.actual_cycle_score or 50.0,
            predicted_action=entry.predicted_action,
            actual_return_pct=entry.actual_performance or 0.0,
            asset_class=state.asset_class,
        )
        for entry in state.evolution_log[-settings.evolution_threshold:]
        if entry.actual_cycle_score is not None
    ]

    if not recent_errors:
        logger.warning("oracle_no_evaluated_errors_yet")
        return

    logger.info("oracle_generating_evolved_prompt", error_count=len(recent_errors))

    # Generate evolved prompt
    evolution_result = await generate_evolved_prompt(
        current_prompt=STRATEGIST_SYSTEM_PROMPT_V1,
        error_history=recent_errors,
        asset_class=state.asset_class,
        llm=llm,
    )

    if not evolution_result:
        logger.error("oracle_evolution_failed_no_result")
        return

    new_prompt = evolution_result.get("new_system_prompt", "")
    if not new_prompt:
        return

    # Compute diff for transparency/audit
    prompt_diff = compute_prompt_diff(STRATEGIST_SYSTEM_PROMPT_V1, new_prompt)
    evolution_result["prompt_diff"] = prompt_diff

    # Shadow backtest
    historical_data = [entry.dict() for entry in state.evolution_log if entry.actual_cycle_score]
    shadow_score = await shadow_backtest(new_prompt, historical_data, llm)

    logger.info(
        "oracle_shadow_backtest_complete",
        shadow_score=shadow_score,
        confidence_in_improvement=evolution_result.get("confidence_in_improvement", 0),
    )

    # Create shadow PromptVersion (not yet active in production)
    evolved_version = PromptVersion(
        agent_role="strategist",
        system_prompt=new_prompt,
        is_active=False,         # Must pass shadow test before activation
        is_shadow=True,
        generation=len(state.evolved_prompt_suggestions) + 2,
        performance_score=shadow_score,
    )

    # Annotate the last evolution log entry
    if state.evolution_log:
        state.evolution_log[-1].prompt_diff = prompt_diff

    state.evolved_prompt_suggestions.append(evolved_version)

    logger.info(
        "oracle_evolution_complete",
        new_version_id=evolved_version.version_id,
        shadow_score=shadow_score,
        diff_lines=len(prompt_diff.splitlines()),
        root_causes=evolution_result.get("root_causes", []),
    )
