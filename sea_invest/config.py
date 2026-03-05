"""
Configuration management for SEA-Invest.
Supports switching LLM providers via environment variables.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── LLM Provider ─────────────────────────────────────────
    llm_provider: Literal["openai", "anthropic", "google", "local"] = "google"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    google_api_key: str = ""

    # ── Agent Model Assignments ───────────────────────────────
    strategist_model: str = "gemini-2.5-flash"
    risk_auditor_model: str = "gemini-2.5-flash"
    oracle_model: str = "gemini-2.5-flash"
    ingestor_model: str = "gemini-2.5-flash"
    devil_advocate_model: str = "gemini-2.5-flash"

    # ── Database ──────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://sea_invest:changeme@localhost:5432/sea_invest"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "sea_invest"
    postgres_user: str = "sea_invest"
    postgres_password: str = "changeme"

    # ── Vector Store ──────────────────────────────────────────
    vector_store_type: Literal["chroma", "faiss", "pinecone"] = "chroma"
    chroma_persist_dir: str = "./data/chroma"
    knowledge_base_dir: str | None = None

    # ── Data Sources ──────────────────────────────────────────
    fred_api_key: str = ""
    alpha_vantage_key: str = ""

    # ── System ────────────────────────────────────────────────
    log_level: str = "INFO"
    max_reflection_cycles: int = 3
    shadow_backtest_days: int = 90
    evolution_threshold: int = 3

    def get_llm(self, role: str = "strategist"):
        """
        Factory method: returns the appropriate LangChain LLM instance.
        Fully modular — swap provider without touching agent code.
        """
        model_map = {
            "strategist": self.strategist_model,
            "risk_auditor": self.risk_auditor_model,
            "oracle": self.oracle_model,
            "ingestor": self.ingestor_model,
            "devil_advocate": self.devil_advocate_model,
        }
        model_name = model_map.get(role, self.strategist_model)

        if self.llm_provider == "openai":
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(model=model_name, api_key=self.openai_api_key, temperature=0.1)

        elif self.llm_provider == "anthropic":
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(model=model_name, api_key=self.anthropic_api_key, temperature=0.1)

        elif self.llm_provider == "google":
            from langchain_google_genai import ChatGoogleGenerativeAI
            return ChatGoogleGenerativeAI(model=model_name, google_api_key=self.google_api_key)

        elif self.llm_provider == "local":
            from langchain_community.llms import Ollama
            return Ollama(model=model_name)

        raise ValueError(f"Unsupported LLM provider: {self.llm_provider}")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton settings instance."""
    return Settings()
