"""
Global State Schema for SEA-Invest
Defines the InvestmentState dataclass that flows through the LangGraph pipeline.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────
# Enumerations
# ─────────────────────────────────────────────

class CyclePhase(str, Enum):
    """Howard Marks' pendulum positions."""
    DEEP_FEAR = "deep_fear"           # 0-15: extreme pessimism, max opportunity
    PESSIMISM = "pessimism"           # 15-35: below-average sentiment
    NEUTRAL = "neutral"               # 35-65: balanced market
    OPTIMISM = "optimism"             # 65-85: above-average sentiment
    EUPHORIA = "euphoria"             # 85-100: extreme greed, max risk


class AssetClass(str, Enum):
    EQUITY = "equity"
    CREDIT = "credit"
    REAL_ESTATE = "real_estate"
    COMMODITY = "commodity"
    MACRO = "macro"
    CRYPTO = "crypto"


class RecommendationAction(str, Enum):
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    REDUCE = "reduce"
    STRONG_SELL = "strong_sell"


# ─────────────────────────────────────────────
# Sub-models
# ─────────────────────────────────────────────

class MarketData(BaseModel):
    """Raw data ingested from external sources."""
    ticker: str
    asset_class: AssetClass
    price: Optional[float] = None
    earnings_summary: Optional[str] = None
    macro_indicators: dict[str, Any] = Field(default_factory=dict)
    raw_sources: list[str] = Field(default_factory=list)
    ingested_at: datetime = Field(default_factory=datetime.utcnow)


class ConsensusView(BaseModel):
    """First-level thinking: what everyone else thinks."""
    narrative: str                         # Dominant market narrative
    expected_action: str                   # What the consensus expects to happen
    sentiment_score: float = Field(..., ge=-1.0, le=1.0)  # -1 fear, +1 greed
    supporting_evidence: list[str] = Field(default_factory=list)


class LogicDelta(BaseModel):
    """Second-level thinking: the gap between consensus and reality."""
    contrarian_thesis: str                 # Why the consensus might be wrong
    asymmetric_insight: str                # What the market is missing
    catalyst_timeline: Optional[str] = None  # When/how the mispricing corrects
    confidence: float = Field(..., ge=0.0, le=1.0)


class CyclePosition(BaseModel):
    """Pendulum position in Howard Marks' market cycle."""
    score: float = Field(..., ge=0.0, le=100.0)   # 0=fear, 100=greed
    phase: CyclePhase
    reasoning: str
    historical_analogs: list[str] = Field(default_factory=list)
    # Track prediction accuracy over time
    previous_prediction: Optional[float] = None
    prediction_error: Optional[float] = None      # Actual - Predicted (filled by Oracle)


class RiskAssessment(BaseModel):
    """Howard Marks-style risk evaluation."""
    permanent_loss_probability: float = Field(..., ge=0.0, le=1.0)
    downside_scenarios: list[str] = Field(default_factory=list)
    margin_of_safety: float = Field(..., ge=-1.0, le=1.0)  # -1 overvalued, +1 deeply undervalued
    key_risks: list[str] = Field(default_factory=list)
    greed_indicators: list[str] = Field(default_factory=list)  # From Reflection Loop


class EvolutionLogEntry(BaseModel):
    """Records performance history of a specific logic version."""
    version_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_role: str                        # Which agent's prompt was changed
    prompt_diff: str                       # What changed vs previous version
    predicted_cycle_score: float
    actual_cycle_score: Optional[float] = None   # Filled after market moves
    predicted_action: RecommendationAction
    actual_performance: Optional[float] = None   # Realized P&L % (filled later)
    was_correct: Optional[bool] = None
    evaluation_date: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PromptVersion(BaseModel):
    """A versioned prompt for an agent role."""
    version_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_role: str
    system_prompt: str
    is_active: bool = True
    is_shadow: bool = False               # Shadow system for A/B testing
    generation: int = 1                   # Version generation number
    parent_version_id: Optional[str] = None
    performance_score: Optional[float] = None   # Aggregate backtest score
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ─────────────────────────────────────────────
# Master State Object
# ─────────────────────────────────────────────

class InvestmentState(BaseModel):
    """
    Global state object flowing through the LangGraph pipeline.
    This is the single source of truth for the entire workflow.
    """
    # Unique identifier for this analysis run
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    ticker: str
    asset_class: AssetClass
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # --- Pipeline Stage Data ---
    market_data: Optional[MarketData] = None

    # Rule B: RAG context injected from Howard Marks' books
    rag_context: str = ""                  # Relevant passages from knowledge base

    # Core state fields (per architecture spec)
    consensus_view: Optional[ConsensusView] = None
    logic_delta: Optional[LogicDelta] = None
    cycle_position: Optional[CyclePosition] = None
    confidence_score: float = 0.0         # 0-1, aggregate agent confidence
    risk_assessment: Optional[RiskAssessment] = None

    # --- Reflection Loop (Rule A) ---
    devil_advocate_critique: Optional[str] = None   # From the "defense attorney" agent
    reflection_cycles: int = 0
    reflection_complete: bool = False

    # --- Final Output ---
    final_recommendation: Optional[RecommendationAction] = None
    investment_memo: str = ""             # Human-readable investment thesis

    # --- Evolution Tracking (Rule C) ---
    evolution_log: list[EvolutionLogEntry] = Field(default_factory=list)
    consecutive_cycle_errors: int = 0     # Triggers Oracle if >= EVOLUTION_THRESHOLD
    oracle_triggered: bool = False
    evolved_prompt_suggestions: list[PromptVersion] = Field(default_factory=list)

    # --- Pipeline Control ---
    errors: list[str] = Field(default_factory=list)
    current_node: str = "ingestor"

    class Config:
        arbitrary_types_allowed = True
