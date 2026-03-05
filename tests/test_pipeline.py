"""
Tests for SEA-Invest Pipeline
Uses mocked LLM responses to test graph logic without actual API calls.
"""
from __future__ import annotations

import json
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from sea_invest.state import (
    AssetClass,
    ConsensusView,
    CyclePhase,
    CyclePosition,
    InvestmentState,
    LogicDelta,
    MarketData,
    RecommendationAction,
    RiskAssessment,
)


# ─────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────

@pytest.fixture
def base_state() -> InvestmentState:
    """A minimal state for testing individual nodes."""
    return InvestmentState(
        ticker="AAPL",
        asset_class=AssetClass.EQUITY,
    )


@pytest.fixture
def state_with_market_data(base_state) -> InvestmentState:
    base_state.market_data = MarketData(
        ticker="AAPL",
        asset_class=AssetClass.EQUITY,
        price=185.0,
        earnings_summary="## Apple Inc Overview\nApple trades at 28x forward PE...",
        macro_indicators={"fed_funds_rate": 5.25, "10y_treasury": 4.35, "vix": 18.2},
    )
    return base_state


@pytest.fixture
def state_with_full_analysis(state_with_market_data) -> InvestmentState:
    state = state_with_market_data
    state.rag_context = "Fear and greed cycle — position conservatively when euphoria is rampant."
    state.consensus_view = ConsensusView(
        narrative="Apple is a safe haven quality tech stock with strong AI optionality.",
        expected_action="Buy on every dip",
        sentiment_score=0.65,
        supporting_evidence=["iPhone cycle resilience", "Services revenue growth"],
    )
    state.logic_delta = LogicDelta(
        contrarian_thesis="AI narrative priced in; iPhone saturation risk in China underweighted.",
        asymmetric_insight="Consensus ignores China regulatory risk and market share loss to Huawei.",
        catalyst_timeline="Next 2 quarters as China iPhone data disappoints consensus.",
        confidence=0.72,
    )
    state.cycle_position = CyclePosition(
        score=72.0,
        phase=CyclePhase.OPTIMISM,
        reasoning="Elevated PE, low vol, strong FOMO-driven tech rally. Late cycle signals.",
        historical_analogs=["2021 tech peak", "2007 pre-GFC optimism"],
    )
    state.confidence_score = 0.68
    state.risk_assessment = RiskAssessment(
        permanent_loss_probability=0.18,
        downside_scenarios=["China revenue -30% scenario", "Regulatory antitrust action"],
        margin_of_safety=-0.12,
        key_risks=["China slowdown", "AI commoditization", "Multiple compression"],
        greed_indicators=["Consensus universally bullish", "Options skew extreme"],
    )
    return state


# ─────────────────────────────────────────────
# State Schema Tests
# ─────────────────────────────────────────────

class TestInvestmentState:
    def test_state_initialization(self, base_state):
        assert base_state.ticker == "AAPL"
        assert base_state.asset_class == AssetClass.EQUITY
        assert base_state.run_id is not None
        assert len(base_state.evolution_log) == 0
        assert base_state.consecutive_cycle_errors == 0

    def test_cycle_phase_mapping(self):
        assert CyclePhase("deep_fear") == CyclePhase.DEEP_FEAR
        assert CyclePhase("euphoria") == CyclePhase.EUPHORIA

    def test_state_serialization(self, state_with_full_analysis):
        """State must be JSON-serializable for LangGraph checkpointing."""
        data = state_with_full_analysis.model_dump_json()
        restored = InvestmentState.model_validate_json(data)
        assert restored.ticker == "AAPL"
        assert restored.cycle_position.score == 72.0


# ─────────────────────────────────────────────
# Devil's Advocate Conditional Edge Tests
# ─────────────────────────────────────────────

class TestReflectionLoop:
    def test_continue_when_under_limit(self, state_with_full_analysis):
        from sea_invest.agents.devil_advocate import should_continue_reflection
        state_with_full_analysis.reflection_cycles = 1
        state_with_full_analysis.risk_assessment.permanent_loss_probability = 0.2
        result = should_continue_reflection(state_with_full_analysis)
        assert result == "proceed_to_synthesis"

    def test_stop_at_max_cycles(self, state_with_full_analysis):
        from sea_invest.agents.devil_advocate import should_continue_reflection
        from sea_invest.config import get_settings
        state_with_full_analysis.reflection_cycles = get_settings().max_reflection_cycles
        result = should_continue_reflection(state_with_full_analysis)
        assert result == "proceed_to_synthesis"

    def test_high_risk_triggers_extra_reflection(self, state_with_full_analysis):
        from sea_invest.agents.devil_advocate import should_continue_reflection
        state_with_full_analysis.reflection_cycles = 0
        state_with_full_analysis.risk_assessment.permanent_loss_probability = 0.6
        result = should_continue_reflection(state_with_full_analysis)
        assert result == "continue_reflection"


# ─────────────────────────────────────────────
# Oracle Diff Engine Tests
# ─────────────────────────────────────────────

class TestOracleDiffEngine:
    def test_prediction_diff_calculation(self):
        from sea_invest.agents.oracle import PredictionDiff
        diff = PredictionDiff(
            predicted_cycle_score=65.0,
            actual_cycle_score=40.0,
            predicted_action=RecommendationAction.HOLD,
            actual_return_pct=15.0,
            asset_class=AssetClass.EQUITY,
        )
        assert diff.cycle_error == pytest.approx(-25.0)
        assert diff.is_significant_error is True
        assert diff.direction_correct is False  # Predicted optimism, market rallied

    def test_correct_direction_prediction(self):
        from sea_invest.agents.oracle import PredictionDiff
        diff = PredictionDiff(
            predicted_cycle_score=20.0,   # Fear zone → buy signal
            actual_cycle_score=45.0,
            predicted_action=RecommendationAction.BUY,
            actual_return_pct=12.5,        # Market rallied ✓
            asset_class=AssetClass.EQUITY,
        )
        assert diff.direction_correct is True

    def test_prompt_diff_generation(self):
        from sea_invest.agents.oracle import compute_prompt_diff
        old = "You are an investor. Focus on value."
        new = "You are a contrarian investor. Focus on value and cycle positioning."
        diff = compute_prompt_diff(old, new)
        assert "contrarian" in diff
        assert "---" in diff or "+++" in diff


# ─────────────────────────────────────────────
# Graph Structure Tests (no LLM calls)
# ─────────────────────────────────────────────

class TestGraphStructure:
    def test_graph_builds_successfully(self):
        """Graph should compile without errors."""
        from sea_invest.graph import build_sea_invest_graph
        graph = build_sea_invest_graph()
        assert graph is not None

    def test_mermaid_output(self):
        from sea_invest.graph import get_graph_mermaid
        mermaid = get_graph_mermaid()
        assert "Ingestor" in mermaid
        assert "Oracle" in mermaid
        assert "Devil's Advocate" in mermaid


# ─────────────────────────────────────────────
# Integration Test (mocked LLM)
# ─────────────────────────────────────────────

class TestPipelineIntegration:
    @pytest.mark.asyncio
    async def test_full_pipeline_with_mocks(self, base_state):
        """
        End-to-end pipeline test with all LLM calls mocked.
        Tests that state flows correctly through all nodes.
        """
        mock_strategist_response = json.dumps({
            "consensus_view": {
                "narrative": "Strong buy consensus on AI growth",
                "expected_action": "Buy aggressively",
                "sentiment_score": 0.75,
                "supporting_evidence": ["Strong earnings", "AI optionality"],
            },
            "logic_delta": {
                "contrarian_thesis": "AI capex bubble risk underweighted",
                "asymmetric_insight": "Market ignores margin pressure from AI investment",
                "catalyst_timeline": "Q2 2025 earnings disappointment",
                "confidence": 0.65,
            },
            "cycle_position": {
                "score": 78.0,
                "phase": "optimism",
                "reasoning": "Late cycle, elevated multiples, low vol",
                "historical_analogs": ["2021 tech peak"],
            },
            "confidence_score": 0.65,
        })

        mock_risk_response = json.dumps({
            "permanent_loss_probability": 0.2,
            "downside_scenarios": ["AI capex write-down", "Multiple compression"],
            "margin_of_safety": -0.15,
            "key_risks": ["Valuation", "China", "Competition"],
            "greed_indicators": ["Universal bullishness"],
            "risk_narrative": "Elevated but manageable risk.",
        })

        # Mock all LLM and external calls
        mock_llm_response = MagicMock()

        with (
            patch("sea_invest.agents.ingestor.PerceptionGateway.collect_all", new_callable=AsyncMock, return_value=[]),
            patch("sea_invest.agents.ingestor.summarize_with_llm", new_callable=AsyncMock, return_value="## Mock Market Digest"),
            patch("sea_invest.rag.knowledge_base.get_vectorstore", return_value=None),
            patch("sea_invest.config.Settings.get_llm") as mock_get_llm,
        ):
            # Mock LLM responses for different agents
            async def mock_ainvoke(messages):
                msg_content = str(messages[0].content)
                if "second-level" in msg_content.lower() or "contrarian" in msg_content.lower():
                    resp = MagicMock()
                    resp.content = mock_strategist_response
                    return resp
                elif "risk" in msg_content.lower() or "permanent" in msg_content.lower():
                    resp = MagicMock()
                    resp.content = mock_risk_response
                    return resp
                else:
                    resp = MagicMock()
                    resp.content = "Mock LLM response for synthesis/critique"
                    return resp

            mock_llm = MagicMock()
            mock_llm.ainvoke = AsyncMock(side_effect=mock_ainvoke)
            mock_get_llm.return_value = mock_llm

            from sea_invest.graph import build_sea_invest_graph
            graph = build_sea_invest_graph()
            final_state_dict = await graph.ainvoke(base_state)
            final_state = InvestmentState.model_validate(final_state_dict)

        # Assertions
        assert final_state.market_data is not None
        assert final_state.market_data.ticker == "AAPL"
        assert final_state.consensus_view is not None
        assert final_state.logic_delta is not None
        assert final_state.cycle_position is not None
        assert final_state.cycle_position.score == 78.0
        assert final_state.risk_assessment is not None
        assert final_state.final_recommendation is not None
        assert final_state.reflection_cycles >= 1
