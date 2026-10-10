"""Central application settings, loaded from environment variables / .env.

Every field here must have a corresponding documented entry in .env.example.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> backend/app/core -> backend/app -> backend -> repo root.
# Resolved explicitly (not left as a bare ".env") so this finds the single root-level .env
# regardless of whether the process was launched from the repo root or from backend/ (both
# are used — see Makefile vs. docker-compose) — otherwise it silently reads no file at all
# when the CWD doesn't happen to contain one, and every setting falls back to its default.
_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- App ---
    app_env: str = Field(default="dev", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    cors_origins: str = Field(default="http://localhost:5173", alias="CORS_ORIGINS")

    # --- Storage paths ---
    data_dir: Path = Field(default=Path("./var/data"), alias="DATA_DIR")
    database_url: str = Field(
        default="sqlite+aiosqlite:///./var/data/veritas.db", alias="DATABASE_URL"
    )

    # --- Hardware / model tier ---
    hardware_tier: str = Field(default="16gb", alias="HARDWARE_TIER")  # "8gb" | "16gb"

    # --- LLM (LiteLLM-routed) ---
    llm_provider: str = Field(default="ollama", alias="LLM_PROVIDER")
    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")
    default_llm_model: str = Field(default="ollama/llama3.2:3b", alias="DEFAULT_LLM_MODEL")
    council_models: str = Field(
        default="ollama/qwen2.5:7b-instruct,ollama/gemma2:2b", alias="COUNCIL_MODELS"
    )
    chairman_model: str = Field(default="ollama/llama3.2:3b", alias="CHAIRMAN_MODEL")
    model_router_latency_budget_ms: int = Field(
        default=12_000, alias="MODEL_ROUTER_LATENCY_BUDGET_MS"
    )
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")

    # --- Embeddings / reranker (baseline defaults; advisor may override per document) ---
    embedding_model: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2", alias="EMBEDDING_MODEL"
    )
    reranker_model: str = Field(
        default="cross-encoder/ms-marco-MiniLM-L-6-v2", alias="RERANKER_MODEL"
    )

    # --- Guard models ---
    guard_model: str = Field(default="ollama/llama-guard3:1b", alias="GUARD_MODEL")
    injection_classifier_model: str = Field(
        default="protectai/deberta-v3-base-prompt-injection-v2",
        alias="INJECTION_CLASSIFIER_MODEL",
    )

    # --- Vector / graph / cache stores ---
    vector_store: str = Field(default="chroma", alias="VECTOR_STORE")  # "chroma" | "qdrant"
    qdrant_url: str = Field(default="http://localhost:6333", alias="QDRANT_URL")
    graph_store: str = Field(default="networkx", alias="GRAPH_STORE")  # "networkx" | "neo4j"
    neo4j_uri: str = Field(default="bolt://localhost:7687", alias="NEO4J_URI")
    neo4j_user: str = Field(default="neo4j", alias="NEO4J_USER")
    neo4j_password: str = Field(default="", alias="NEO4J_PASSWORD")
    redis_url: str = Field(default="", alias="REDIS_URL")  # empty => in-memory fallback
    semantic_cache_enabled: bool = Field(default=True, alias="SEMANTIC_CACHE_ENABLED")

    # --- PII vault ---
    pii_vault_key: str = Field(default="", alias="PII_VAULT_KEY")  # Fernet key, required in prod
    pii_hmac_secret: str = Field(default="dev-only-change-me", alias="PII_HMAC_SECRET")

    # --- URL ingestion / SSRF guard ---
    scrape_timeout_seconds: int = Field(default=10, alias="SCRAPE_TIMEOUT_SECONDS")
    scrape_max_bytes: int = Field(default=5 * 1024 * 1024, alias="SCRAPE_MAX_BYTES")
    scrape_max_crawl_depth: int = Field(default=2, alias="SCRAPE_MAX_CRAWL_DEPTH")
    scrape_max_pages: int = Field(default=20, alias="SCRAPE_MAX_PAGES")

    # --- Guardrails / rate limiting ---
    rate_limit_per_minute: int = Field(default=60, alias="RATE_LIMIT_PER_MINUTE")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def council_model_list(self) -> list[str]:
        return [m.strip() for m in self.council_models.split(",") if m.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
