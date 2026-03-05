"""
Synthesis Agent
Integrates all agent outputs into a final investment memo and recommendation.
Runs after the Reflection Loop is complete.
"""
from __future__ import annotations

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from sea_invest.config import get_settings
from sea_invest.state import InvestmentState, RecommendationAction

logger = structlog.get_logger(__name__)
settings = get_settings()


SYNTHESIS_SYSTEM_PROMPT = """You are the Chief Investment Officer synthesizing a final 
investment decision. You have received input from:
1. Strategist — second-level thinking and cycle position
2. Risk Auditor — downside scenarios and permanent loss probability  
3. Devil's Advocate — critique and greed challenge (completed {reflection_cycles} reflection cycles)

## Output Requirements
生成简洁的中文投资备忘录，包含以下部分：

### 执行摘要（2-3句）
### 多头观点
### 空头观点（魔鬼代言人总结）
### 风险收益评估
### 周期位置与背景
### 投资建议：[STRONG_BUY | BUY | HOLD | REDUCE | STRONG_SELL]
### 信心水平：[HIGH | MEDIUM | LOW]
### 关键监控触发器（什么情况会改变你的观点）
### 📈 标的客观数据
[在最后附上之前分析链路中收集的股票标的客观数据摘要：当前价格、估值水平、财务健康状况、重要宏观指标等]

## Decision Rules (Howard Marks-encoded)
- Never recommend STRONG_BUY if cycle_score > 75 (euphoria territory)
- Never recommend STRONG_SELL if cycle_score < 25 (deep fear territory)
- Permanent loss probability > 0.5 → maximum HOLD recommendation
- Margin of safety < -0.2 → must recommend REDUCE or lower
"""


async def synthesis_node(state: InvestmentState) -> InvestmentState:
    """Final synthesis node: produces investment memo and recommendation."""
    logger.info("synthesis_start", ticker=state.ticker, run_id=state.run_id)
    state.current_node = "synthesis"

    llm = settings.get_llm("strategist")

    context = f"""
**标的**: {state.ticker} | **资产类别**: {state.asset_class.value}

**周期位置**: {state.cycle_position.score:.1f}/100 ({state.cycle_position.phase.value})
→ {state.cycle_position.reasoning}

**市场共识（第一层思维）**: {state.consensus_view.narrative if state.consensus_view else 'N/A'}

**逆向观点（第二层思维）**: {state.logic_delta.contrarian_thesis if state.logic_delta else 'N/A'}

**风险概况**:
- 永久性损失概率: {state.risk_assessment.permanent_loss_probability:.1%}
- 安全边际: {state.risk_assessment.margin_of_safety:.2f}
- 关键风险: {', '.join(state.risk_assessment.key_risks) if state.risk_assessment else 'N/A'}

**魔鬼代言人批评（经过 {state.reflection_cycles} 轮反思）**:
{state.devil_advocate_critique or '未生成批评。'}

**整体信心**: {state.confidence_score:.2f}
"""

    # Add objective market data if available
    objective_data = ""
    if state.market_data:
        objective_data = "\n\n**标的客观数据**:\n"
        if state.market_data.price:
            objective_data += f"- 当前价格: {state.market_data.price}\n"
        
        if state.market_data.earnings_summary:
            objective_data += f"\n{state.market_data.earnings_summary}\n"
        
        if state.market_data.macro_indicators:
            objective_data += "\n**宏观经济指标**:\n"
            macro_names = {
                "FEDFUNDS": "联邦基金利率",
                "CPIAUCSL": "CPI 消费者物价指数",
                "UNRATE": "失业率",
                "GS10": "10年期国债收益率",
                "T10Y2Y": "2年期-10年期国债利差",
                "BAMLH0A0HYM2": "高收益债利差",
                "VIXCLS": "VIX 波动率指数"
            }
            for key, value in state.market_data.macro_indicators.items():
                display_name = macro_names.get(key, key)
                objective_data += f"- {display_name}: {value}\n"

    system = SYNTHESIS_SYSTEM_PROMPT.format(reflection_cycles=state.reflection_cycles)
    messages = [SystemMessage(content=system), HumanMessage(content=context + objective_data + "\n\n生成中文投资备忘录。")]

    try:
        response = await llm.ainvoke(messages)
        raw_content = response.content
        if isinstance(raw_content, list):
            raw_content = " ".join(c.get("text", str(c)) if isinstance(c, dict) else str(c) for c in raw_content)
        state.investment_memo = str(raw_content)

        # Extract recommendation from memo
        content_upper = state.investment_memo.upper()
        for action in RecommendationAction:
            if action.value.upper() in content_upper:
                state.final_recommendation = action
                break
        else:
            state.final_recommendation = RecommendationAction.HOLD  # Safe default

        logger.info(
            "synthesis_complete",
            ticker=state.ticker,
            recommendation=state.final_recommendation.value,
        )
    except Exception as e:
        logger.error("synthesis_error", error=str(e))
        state.errors.append(f"Synthesis error: {e}")
        state.final_recommendation = RecommendationAction.HOLD

    return state
