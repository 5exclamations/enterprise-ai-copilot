"""Application settings, loaded from environment variables / .env."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- storage -----------------------------------------------------------
    # SQLite works out of the box; use Postgres + pgvector for the real stack.
    database_url: str = "sqlite:///./copilot.db"
    redis_url: str | None = None  # optional: shared rate limiting

    # --- LLM ---------------------------------------------------------------
    llm_provider: str = "mock"  # mock | ollama | openai | anthropic
    llm_model: str = ""
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"  # any OpenAI-compatible server (Ollama, vLLM...)
    anthropic_api_key: str | None = None
    anthropic_base_url: str = "https://api.anthropic.com"
    llm_timeout_seconds: float = 60.0
    # Local Ollama server (native /api/chat and /api/embed), used when LLM_PROVIDER / EMBEDDING_PROVIDER = ollama.
    ollama_base_url: str = "http://localhost:11434"
    ollama_timeout_seconds: float = 300.0  # local small-GPU/CPU inference is slow; be patient
    ollama_num_ctx: int = 4096  # context window requested per call (bounds VRAM use)
    ollama_keep_alive: str = "10m"  # keep the model resident between calls
    # Optional $/1M-token overrides so cost estimates are explicit, never guessed.
    llm_price_input_per_mtok: float | None = None
    llm_price_output_per_mtok: float | None = None

    # --- embeddings --------------------------------------------------------
    embedding_provider: str = "hashing"  # hashing | ollama | openai (OpenAI-compatible /embeddings)
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 256  # vector column width; changing it needs `alembic upgrade head` + `python -m app.reindex`
    # Asymmetric embedding models (e.g. nomic-embed-text) need task prefixes; empty = none.
    embedding_query_prefix: str = ""
    embedding_document_prefix: str = ""

    # --- agent / retrieval -------------------------------------------------
    max_agent_steps: int = 5
    retrieval_top_k: int = 5
    quarantine_injected_chunks: bool = True

    # --- limits ------------------------------------------------------------
    max_message_chars: int = 2000
    max_upload_bytes: int = 10 * 1024 * 1024
    rate_limit_per_minute: int = 120
    action_ttl_minutes: int = 30

    # Demo mode exposes seeded demo API keys to the login screen. MUST be false in production.
    demo_mode: bool = True

    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
