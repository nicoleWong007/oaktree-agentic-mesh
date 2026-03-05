"""
PostgreSQL Persistence Layer for SEA-Invest
============================================
Stores:
1. analysis_runs        — Each pipeline execution and its final state
2. logic_versions       — Prompt versions (PromptVersion objects)
3. evolution_log        — Per-run predictions with actual outcomes
4. cycle_accuracy       — Aggregate accuracy metrics by asset class
5. shadow_test_results  — Results of Oracle's shadow backtest runs

Design decision: Uses SQLAlchemy async ORM + asyncpg for non-blocking DB ops.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from sea_invest.config import get_settings

settings = get_settings()

# ─────────────────────────────────────────────
# Database Engine
# ─────────────────────────────────────────────

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_db() -> AsyncSession:
    """Dependency injection: use in FastAPI or service layer."""
    async with AsyncSessionLocal() as session:
        yield session


# ─────────────────────────────────────────────
# ORM Models
# ─────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


class AnalysisRun(Base):
    """
    Records each complete pipeline execution.
    Primary source of truth for what was predicted and when.
    """
    __tablename__ = "analysis_runs"

    id = Column(String, primary_key=True)              # run_id (UUID)
    ticker = Column(String(20), nullable=False, index=True)
    asset_class = Column(String(50), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Predictions made
    predicted_cycle_score = Column(Float)
    predicted_phase = Column(String(50))
    final_recommendation = Column(String(50))
    confidence_score = Column(Float)

    # Contrarian thesis (for future diff against reality)
    consensus_narrative = Column(Text)
    contrarian_thesis = Column(Text)
    asymmetric_insight = Column(Text)

    # Risk metrics
    permanent_loss_probability = Column(Float)
    margin_of_safety = Column(Float)

    # Full investment memo
    investment_memo = Column(Text)

    # Reflection quality
    reflection_cycles = Column(Integer, default=0)
    devil_advocate_critique = Column(Text)

    # Errors during this run
    pipeline_errors = Column(JSON, default=list)

    # ------- Filled retroactively when market data is available -------
    actual_cycle_score = Column(Float, nullable=True)
    actual_return_30d = Column(Float, nullable=True)    # 30-day return %
    actual_return_90d = Column(Float, nullable=True)    # 90-day return %
    cycle_error = Column(Float, nullable=True)          # actual - predicted
    direction_correct = Column(Boolean, nullable=True)
    evaluation_date = Column(DateTime, nullable=True)

    # Oracle meta
    consecutive_errors_at_time = Column(Integer, default=0)
    oracle_triggered = Column(Boolean, default=False)


class LogicVersion(Base):
    """
    Stores versioned System Prompts for each agent role.
    Enables A/B testing between production and shadow (Oracle-evolved) prompts.
    
    Key design: parent_version_id creates a linked list of prompt evolution lineage.
    """
    __tablename__ = "logic_versions"

    id = Column(String, primary_key=True)              # version_id (UUID)
    agent_role = Column(String(50), nullable=False, index=True)
    generation = Column(Integer, nullable=False, default=1)
    system_prompt = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True, index=True)
    is_shadow = Column(Boolean, default=False, index=True)
    parent_version_id = Column(String, nullable=True)  # FK to self

    # Performance metrics (aggregated from evolution_log)
    performance_score = Column(Float, nullable=True)
    direction_accuracy = Column(Float, nullable=True)   # % directionally correct
    mean_cycle_error = Column(Float, nullable=True)     # lower is better
    sample_count = Column(Integer, default=0)

    # What changed from parent (unified diff)
    prompt_diff = Column(Text, nullable=True)

    # Oracle's reasoning for this evolution
    oracle_reasoning = Column(Text, nullable=True)
    oracle_root_causes = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    promoted_at = Column(DateTime, nullable=True)       # When shadow → production


class EvolutionLogRecord(Base):
    """
    Per-run evolution tracking. Associates a prediction with a logic version,
    and later stores the actual market outcome for Oracle's Diff Engine.
    """
    __tablename__ = "evolution_log"

    id = Column(String, primary_key=True)
    run_id = Column(String, nullable=False, index=True)
    ticker = Column(String(20), nullable=False, index=True)
    asset_class = Column(String(50), nullable=False, index=True)
    logic_version_id = Column(String, nullable=True)   # Which prompt was used

    # Prediction
    predicted_cycle_score = Column(Float, nullable=False)
    predicted_action = Column(String(50), nullable=False)
    prediction_confidence = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Actual outcome (filled by cron job / outcome recorder)
    actual_cycle_score = Column(Float, nullable=True)
    actual_return_pct = Column(Float, nullable=True)
    cycle_error = Column(Float, nullable=True)
    direction_correct = Column(Boolean, nullable=True)
    evaluated_at = Column(DateTime, nullable=True)

    # Consecutive error tracking (updated when actual is filled)
    consecutive_errors_asset_class = Column(Integer, default=0)


class CycleAccuracy(Base):
    """
    Aggregate accuracy metrics by asset class and logic version.
    Used by Oracle to quickly check if evolution threshold is reached.
    """
    __tablename__ = "cycle_accuracy"

    id = Column(Integer, primary_key=True, autoincrement=True)
    asset_class = Column(String(50), nullable=False, index=True)
    logic_version_id = Column(String, nullable=False)

    total_predictions = Column(Integer, default=0)
    correct_directions = Column(Integer, default=0)
    direction_accuracy = Column(Float)                  # correct / total
    mean_cycle_error = Column(Float)
    std_cycle_error = Column(Float)
    consecutive_errors = Column(Integer, default=0)     # ← Oracle monitors this

    last_updated = Column(DateTime, default=datetime.utcnow)


class ShadowTestResult(Base):
    """Stores results of Oracle's shadow backtest for evolved prompts."""
    __tablename__ = "shadow_test_results"

    id = Column(String, primary_key=True)
    shadow_version_id = Column(String, nullable=False, index=True)
    baseline_version_id = Column(String, nullable=False)
    asset_class = Column(String(50), nullable=False)

    # Backtest period
    test_start_date = Column(DateTime, nullable=False)
    test_end_date = Column(DateTime, nullable=False)
    historical_runs_tested = Column(Integer, default=0)

    # Performance comparison
    shadow_direction_accuracy = Column(Float)
    baseline_direction_accuracy = Column(Float)
    shadow_mean_error = Column(Float)
    baseline_mean_error = Column(Float)
    improvement_pct = Column(Float)                     # Relative improvement

    # Decision
    promoted_to_production = Column(Boolean, default=False)
    promotion_rationale = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)


# ─────────────────────────────────────────────
# Repository: Data Access Layer
# ─────────────────────────────────────────────

class AnalysisRepository:
    """All database operations for the SEA-Invest pipeline."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_analysis_run(self, state) -> AnalysisRun:
        """Persist a completed pipeline run."""
        from sea_invest.state import InvestmentState
        record = AnalysisRun(
            id=state.run_id,
            ticker=state.ticker,
            asset_class=state.asset_class.value,
            created_at=state.created_at,
            predicted_cycle_score=state.cycle_position.score if state.cycle_position else None,
            predicted_phase=state.cycle_position.phase.value if state.cycle_position else None,
            final_recommendation=state.final_recommendation.value if state.final_recommendation else None,
            confidence_score=state.confidence_score,
            consensus_narrative=state.consensus_view.narrative if state.consensus_view else None,
            contrarian_thesis=state.logic_delta.contrarian_thesis if state.logic_delta else None,
            asymmetric_insight=state.logic_delta.asymmetric_insight if state.logic_delta else None,
            permanent_loss_probability=state.risk_assessment.permanent_loss_probability if state.risk_assessment else None,
            margin_of_safety=state.risk_assessment.margin_of_safety if state.risk_assessment else None,
            investment_memo=state.investment_memo,
            reflection_cycles=state.reflection_cycles,
            devil_advocate_critique=state.devil_advocate_critique,
            pipeline_errors=state.errors,
            consecutive_errors_at_time=state.consecutive_cycle_errors,
            oracle_triggered=state.oracle_triggered,
        )
        self.session.add(record)
        await self.session.commit()
        return record

    async def save_evolution_log(self, state) -> list[EvolutionLogRecord]:
        """Persist evolution log entries from the Oracle."""
        records = []
        for entry in state.evolution_log:
            record = EvolutionLogRecord(
                id=entry.version_id,
                run_id=state.run_id,
                ticker=state.ticker,
                asset_class=state.asset_class.value,
                predicted_cycle_score=entry.predicted_cycle_score,
                predicted_action=entry.predicted_action.value,
                prediction_confidence=state.confidence_score,
            )
            self.session.add(record)
            records.append(record)
        await self.session.commit()
        return records

    async def get_consecutive_errors(self, asset_class: str) -> int:
        """Query consecutive cycle-positioning errors for an asset class."""
        from sqlalchemy import select
        result = await self.session.execute(
            select(CycleAccuracy.consecutive_errors)
            .where(CycleAccuracy.asset_class == asset_class)
            .order_by(CycleAccuracy.last_updated.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return row or 0

    async def record_actual_outcome(
        self,
        run_id: str,
        actual_cycle_score: float,
        actual_return_pct: float,
        evaluation_date: datetime,
    ) -> None:
        """
        Called by the outcome-recording cron job when market data is available.
        Updates the prediction record and refreshes consecutive error count.
        """
        from sqlalchemy import update

        # Update analysis run
        await self.session.execute(
            update(AnalysisRun)
            .where(AnalysisRun.id == run_id)
            .values(
                actual_cycle_score=actual_cycle_score,
                actual_return_pct=actual_return_pct,
                cycle_error=actual_cycle_score,   # Will be computed properly
                evaluation_date=evaluation_date,
            )
        )

        # Update evolution log
        await self.session.execute(
            update(EvolutionLogRecord)
            .where(EvolutionLogRecord.run_id == run_id)
            .values(
                actual_cycle_score=actual_cycle_score,
                actual_return_pct=actual_return_pct,
                evaluated_at=evaluation_date,
            )
        )

        await self.session.commit()

    async def save_logic_version(self, prompt_version) -> LogicVersion:
        """Save a new prompt version (including Oracle-evolved shadow versions)."""
        record = LogicVersion(
            id=prompt_version.version_id,
            agent_role=prompt_version.agent_role,
            generation=prompt_version.generation,
            system_prompt=prompt_version.system_prompt,
            is_active=prompt_version.is_active,
            is_shadow=prompt_version.is_shadow,
            parent_version_id=prompt_version.parent_version_id,
            performance_score=prompt_version.performance_score,
        )
        self.session.add(record)
        await self.session.commit()
        return record

    async def promote_shadow_to_production(
        self, shadow_version_id: str, rationale: str
    ) -> None:
        """
        Oracle promotes a shadow prompt to production after successful backtest.
        Deactivates current production version, activates the evolved version.
        """
        from sqlalchemy import select, update

        # Find and deactivate current production version
        shadow = await self.session.get(LogicVersion, shadow_version_id)
        if not shadow:
            raise ValueError(f"Shadow version {shadow_version_id} not found")

        await self.session.execute(
            update(LogicVersion)
            .where(
                LogicVersion.agent_role == shadow.agent_role,
                LogicVersion.is_active == True,
                LogicVersion.is_shadow == False,
            )
            .values(is_active=False)
        )

        # Promote shadow to production
        await self.session.execute(
            update(LogicVersion)
            .where(LogicVersion.id == shadow_version_id)
            .values(is_active=True, is_shadow=False, promoted_at=datetime.utcnow())
        )

        await self.session.commit()


async def init_db():
    """Create all tables. Run once at startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
