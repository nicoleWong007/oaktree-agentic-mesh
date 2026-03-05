"""
SEA-Invest LangGraph Pipeline Definition
==========================================
Defines the directed graph of agents with conditional edges and the Reflection Loop.

Graph Topology:
    START
      ↓
    [Ingestor] → async data fetch & normalize
      ↓
    [RAG Injector] → inject Howard Marks knowledge
      ↓
    [Strategist] → second-level thinking + cycle positioning
      ↓
    [Risk Auditor] → permanent loss probability + greed flags
      ↓
    [Devil's Advocate] ←──────────────────────────────╮
      ↓                                                │
    {should_continue_reflection?} ──────────────────→ ╯ (loop up to N cycles)
      ↓ (proceed_to_synthesis)
    [Synthesis] → investment memo + recommendation
      ↓
    [Oracle] → log prediction; trigger evolution if threshold met
      ↓
    END
"""
from __future__ import annotations

from typing import Literal

import structlog
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from sea_invest.agents.devil_advocate import devil_advocate_node, should_continue_reflection
from sea_invest.agents.ingestor import ingestor_node
from sea_invest.agents.oracle import oracle_node
from sea_invest.agents.risk_auditor import risk_auditor_node
from sea_invest.agents.strategist import strategist_node
from sea_invest.agents.synthesis import synthesis_node
from sea_invest.rag.knowledge_base import inject_rag_context
from sea_invest.state import AssetClass, InvestmentState

logger = structlog.get_logger(__name__)


# ─────────────────────────────────────────────
# Node Wrapper (add logging + error isolation)
# ─────────────────────────────────────────────

def _wrap_node(fn, name: str):
    """Wrap a node function with error isolation and logging."""
    async def wrapped(state: InvestmentState) -> InvestmentState:
        try:
            return await fn(state)
        except Exception as e:
            logger.error(f"node_unhandled_error", node=name, error=str(e), run_id=state.run_id)
            state.errors.append(f"[{name}] Unhandled error: {e}")
            return state
    wrapped.__name__ = name
    return wrapped


# ─────────────────────────────────────────────
# Graph Builder
# ─────────────────────────────────────────────

def build_sea_invest_graph() -> CompiledStateGraph:
    """
    Constructs and compiles the SEA-Invest LangGraph state machine.
    
    Returns a compiled graph ready for invocation:
        graph = build_sea_invest_graph()
        result = await graph.ainvoke(initial_state)
    """
    workflow = StateGraph(InvestmentState)

    # ── Register Nodes ─────────────────────────────────────
    workflow.add_node("ingestor",       _wrap_node(ingestor_node, "ingestor"))
    workflow.add_node("rag_injector",   _wrap_node(inject_rag_context, "rag_injector"))
    workflow.add_node("strategist",     _wrap_node(strategist_node, "strategist"))
    workflow.add_node("risk_auditor",   _wrap_node(risk_auditor_node, "risk_auditor"))
    workflow.add_node("devil_advocate", _wrap_node(devil_advocate_node, "devil_advocate"))
    workflow.add_node("synthesis",      _wrap_node(synthesis_node, "synthesis"))
    workflow.add_node("oracle",         _wrap_node(oracle_node, "oracle"))

    # ── Linear Edges ───────────────────────────────────────
    workflow.add_edge(START, "ingestor")
    workflow.add_edge("ingestor", "rag_injector")
    workflow.add_edge("rag_injector", "strategist")
    workflow.add_edge("strategist", "risk_auditor")
    workflow.add_edge("risk_auditor", "devil_advocate")

    # ── Reflection Loop (Rule A) ───────────────────────────
    # Conditional edge: repeat devil_advocate or proceed to synthesis
    workflow.add_conditional_edges(
        "devil_advocate",
        should_continue_reflection,
        {
            "continue_reflection": "devil_advocate",   # Loop back
            "proceed_to_synthesis": "synthesis",        # Exit loop
        },
    )

    # ── Post-Synthesis Linear Path ─────────────────────────
    workflow.add_edge("synthesis", "oracle")
    workflow.add_edge("oracle", END)

    # ── Compile ────────────────────────────────────────────
    compiled = workflow.compile()
    logger.info("graph_compiled", nodes=list(workflow.nodes.keys()))
    return compiled


# ─────────────────────────────────────────────
# Graph Visualization (for documentation)
# ─────────────────────────────────────────────

def get_graph_mermaid() -> str:
    """Return a Mermaid diagram string for the pipeline."""
    return """
```mermaid
flowchart TD
    S([START]) --> IN[🔍 Ingestor\\nAsync multi-source data fetch]
    IN --> RAG[📚 RAG Injector\\nHoward Marks knowledge base]
    RAG --> ST[🧠 Strategist\\nSecond-level thinking\\nCycle positioning]
    ST --> RA[⚠️ Risk Auditor\\nPermanent loss probability\\nGreed flags identification]
    RA --> DA[⚖️ Devil's Advocate\\nReflection Loop\\nChallenge greed]
    DA -->|continue\\nreflection| DA
    DA -->|proceed to\\nsynthesis| SY[📝 Synthesis\\nInvestment memo\\nFinal recommendation]
    SY --> OR[🔮 Oracle\\nLog prediction\\nEvolution engine]
    OR --> E([END])
    
    style S fill:#1a1a2e,color:#e0e0e0
    style E fill:#1a1a2e,color:#e0e0e0
    style IN fill:#16213e,color:#4fc3f7
    style RAG fill:#16213e,color:#80cbc4
    style ST fill:#0f3460,color:#f8bbd0
    style RA fill:#0f3460,color:#ffcc80
    style DA fill:#533483,color:#ffffff
    style SY fill:#0d7377,color:#ffffff
    style OR fill:#8b1a1a,color:#ffffff
```
"""
