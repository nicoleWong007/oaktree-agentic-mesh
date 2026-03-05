"""
Ingestor Agent
Fetches data from multiple sources (earnings, news, macro) and normalizes to Markdown.
Uses async IO for concurrent data fetching.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

import aiohttp
import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from sea_invest.config import get_settings
from sea_invest.state import AssetClass, InvestmentState, MarketData
from sea_invest.perception.gateway import PerceptionGateway
from sea_invest.perception.yahoo_driver import YahooFinanceDriver
from sea_invest.perception.macro_driver import MacroDriver

logger = structlog.get_logger(__name__)
settings = get_settings()




async def summarize_with_llm(raw_data: dict, ticker: str, asset_class: AssetClass) -> str:
    """Use a lightweight LLM to normalize raw data into a structured Markdown digest."""
    llm = settings.get_llm("ingestor")
    system_prompt = """You are a financial data normalizer. Convert raw financial data into 
a structured Markdown report with these sections:
## Company/Asset Overview
## Recent Price Action
## Key Financial Metrics  
## Macro Backdrop Relevance
Be factual and concise. No opinions. No recommendations."""

    user_content = f"""
Ticker: {ticker}
Asset Class: {asset_class.value}
Raw Data:
{str(raw_data)[:4000]}

Generate the structured Markdown digest.
"""
    messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_content)]
    response = await llm.ainvoke(messages)
    content = response.content
    if isinstance(content, list):
        content = " ".join(c.get("text", str(c)) if isinstance(c, dict) else str(c) for c in content)
    return str(content)


# ─────────────────────────────────────────────
# Main Ingestor Node
# ─────────────────────────────────────────────

async def ingestor_node(state: InvestmentState) -> InvestmentState:
    """
    LangGraph Node: Ingestor
    Concurrently fetches data from all sources, normalizes to Markdown,
    and populates state.market_data.
    """
    logger.info("ingestor_start", ticker=state.ticker, run_id=state.run_id)
    state.current_node = "ingestor"

    gateway = PerceptionGateway()
    yahoo_driver = YahooFinanceDriver(timeout=15.0)
    macro_driver = MacroDriver(timeout=15.0, api_key=settings.fred_api_key)
    
    gateway.register(yahoo_driver)
    gateway.register(macro_driver)
    
    scan_plan = {
        "YahooFinance": [state.ticker],
        "FREDMacro": [
            "FEDFUNDS", "CPIAUCSL", "UNRATE", 
            "GS10", "T10Y2Y", "BAMLH0A0HYM2", "VIXCLS"
        ]
    }
    
    # Run perception gateway to fetch fundamentals and macro data
    perception_data = await gateway.collect_all(scan_plan)
    
    yahoo_data = {}
    macro_data = {}
    for moment in perception_data:
        if moment.source_name == "YahooFinance" and moment.payload.get("ticker", "").upper() == state.ticker.upper():
            yahoo_data = moment.payload
        elif moment.source_name == "FREDMacro":
            indicator = moment.payload.get("indicator")
            if indicator:
                macro_data[indicator] = moment.payload.get("value")

    # Combine raw data
    raw_combined = {
        "ticker": state.ticker,
        "fundamentals": yahoo_data,
        "macro_indicators": macro_data,
        "fetched_at": datetime.utcnow().isoformat(),
    }

    # Normalize to Markdown via LLM
    earnings_summary = await summarize_with_llm(raw_combined, state.ticker, state.asset_class)

    state.market_data = MarketData(
        ticker=state.ticker,
        asset_class=state.asset_class,
        price=yahoo_data.get("price"),
        earnings_summary=earnings_summary,
        macro_indicators=macro_data,
        raw_sources=["yahoo_finance", "fred"],
    )

    logger.info("ingestor_complete", ticker=state.ticker, data_length=len(earnings_summary))
    return state
