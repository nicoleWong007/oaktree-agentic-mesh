"""
SEA-Invest Main Entry Point
Run a complete investment analysis pipeline for a given ticker.

Usage:
    python -m sea_invest.main --ticker AAPL --asset-class equity
    python -m sea_invest.main --ticker HYG --asset-class credit
    python -m sea_invest.main --ticker GLD --asset-class commodity
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime

import structlog
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from sea_invest.config import get_settings
from sea_invest.graph import build_sea_invest_graph
from sea_invest.persistence.database import AnalysisRepository, AsyncSessionLocal, init_db
from sea_invest.state import AssetClass, InvestmentState

logger = structlog.get_logger(__name__)
console = Console()
settings = get_settings()


async def run_analysis(ticker: str, asset_class: AssetClass, consecutive_errors: int = 0) -> InvestmentState:
    """
    Execute the complete SEA-Invest pipeline for a given asset.
    
    Args:
        ticker: Asset ticker symbol (e.g., 'AAPL', 'HYG', 'GLD')
        asset_class: AssetClass enum value
        consecutive_errors: Current consecutive error count (from DB)
    
    Returns:
        Completed InvestmentState with all agent outputs
    """
    console.print(Panel(
        f"[bold cyan]SEA-Invest Analysis[/bold cyan]\n"
        f"Ticker: [yellow]{ticker}[/yellow] | Asset Class: [green]{asset_class.value}[/green]\n"
        f"Run started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        title="🌊 SEA-Invest",
        border_style="cyan",
    ))

    # Initialize state
    initial_state = InvestmentState(
        ticker=ticker,
        asset_class=asset_class,
        consecutive_cycle_errors=consecutive_errors,
    )

    # Build and run graph
    graph = build_sea_invest_graph()

    console.print("\n[dim]Running pipeline nodes...[/dim]")
    
    final_state_dict = await graph.ainvoke(initial_state)
    final_state = InvestmentState.model_validate(final_state_dict)

    return final_state


def display_results(state: InvestmentState) -> None:
    """Pretty-print the final investment analysis to console."""
    
    # Header table
    table = Table(title="📊 Analysis Summary", border_style="blue")
    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")

    if state.cycle_position:
        table.add_row("Cycle Score", f"{state.cycle_position.score:.1f}/100 ({state.cycle_position.phase.value})")
    if state.consensus_view:
        table.add_row("Sentiment", f"{state.consensus_view.sentiment_score:.2f} (-1=fear, +1=greed)")
    if state.risk_assessment:
        table.add_row("Permanent Loss Risk", f"{state.risk_assessment.permanent_loss_probability:.1%}")
        table.add_row("Margin of Safety", f"{state.risk_assessment.margin_of_safety:.2f}")
    table.add_row("Confidence Score", f"{state.confidence_score:.2f}")
    table.add_row("Reflection Cycles", str(state.reflection_cycles))
    table.add_row("Oracle Triggered", "⚠️ YES" if state.oracle_triggered else "✅ No")

    if state.final_recommendation:
        rec_color = {
            "strong_buy": "bold green",
            "buy": "green",
            "hold": "yellow",
            "reduce": "red",
            "strong_sell": "bold red",
        }.get(state.final_recommendation.value, "white")
        table.add_row("RECOMMENDATION", f"[{rec_color}]{state.final_recommendation.value.upper()}[/{rec_color}]")

    console.print(table)

    # Investment memo
    if state.investment_memo:
        console.print("\n")
        console.print(Panel(
            Markdown(state.investment_memo),
            title="📝 Investment Memorandum",
            border_style="green",
        ))

    # Errors
    if state.errors:
        console.print("\n[bold red]Pipeline Errors:[/bold red]")
        for err in state.errors:
            console.print(f"  ❌ {err}")

    # Oracle evolution
    if state.oracle_triggered and state.evolved_prompt_suggestions:
        console.print("\n[bold magenta]🔮 Oracle Evolution Triggered![/bold magenta]")
        for v in state.evolved_prompt_suggestions:
            console.print(f"  Shadow Version ID: {v.version_id}")
            console.print(f"  Generation: {v.generation}")
            console.print(f"  Shadow Backtest Score: {v.performance_score:.2f}")


async def persist_results(state: InvestmentState) -> None:
    """Save analysis results and evolution log to PostgreSQL."""
    try:
        async with AsyncSessionLocal() as session:
            repo = AnalysisRepository(session)
            await repo.save_analysis_run(state)
            await repo.save_evolution_log(state)

            # Persist any evolved prompt versions
            for pv in state.evolved_prompt_suggestions:
                await repo.save_logic_version(pv)

        logger.info("results_persisted", run_id=state.run_id)
        console.print(f"\n[dim]✅ Results persisted to DB. Run ID: {state.run_id}[/dim]")
    except Exception as e:
        console.print(f"\n[yellow]⚠️ DB persistence failed (pipeline still succeeded): {e}[/yellow]")


async def main_async(ticker: str, asset_class_str: str, skip_db: bool = False) -> None:
    # Initialize DB schema
    if not skip_db:
        try:
            await init_db()
        except Exception as e:
            console.print(f"[yellow]DB init skipped: {e}[/yellow]")

    # Map string to enum
    try:
        asset_class = AssetClass(asset_class_str)
    except ValueError:
        console.print(f"[red]Invalid asset class: {asset_class_str}[/red]")
        console.print(f"Valid values: {[a.value for a in AssetClass]}")
        sys.exit(1)

    # Run analysis
    state = await run_analysis(ticker, asset_class)

    # Display results
    display_results(state)

    # Persist
    if not skip_db:
        await persist_results(state)


def main():
    parser = argparse.ArgumentParser(description="SEA-Invest: Self-Evolving Agentic Investment Workflow")
    parser.add_argument("--ticker", required=True, help="Asset ticker (e.g., AAPL, HYG)")
    parser.add_argument("--asset-class", default="equity",
                        choices=[a.value for a in AssetClass],
                        help="Asset class")
    parser.add_argument("--skip-db", action="store_true",
                        help="Skip database persistence (useful for testing)")
    args = parser.parse_args()

    asyncio.run(main_async(args.ticker, args.asset_class, args.skip_db))


if __name__ == "__main__":
    main()
