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
    # After a document is ready, measure the main strategies on a few of its own questions and
    # answer it with the best one. About two minutes of background model time per upload,
    # always behind chat and user-started jobs. Off under tests unless a test turns it on.
    auto_measure_on_ingest: bool | None = Field(default=None, alias="AUTO_MEASURE_ON_INGEST")

    @property
    def auto_measure_enabled(self) -> bool:
        if self.auto_measure_on_ingest is not None:
            return self.auto_measure_on_ingest
        return self.app_env != "test"

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
    council_models: str = Field(default="ollama/gemma2:2b,ollama/gemma3:4b", alias="COUNCIL_MODELS")
    # Off by default: harder questions and the agent's grading steps stay on the one answer
    # model instead of loading a second, larger one next to it. On a 16 GB machine two
    # resident chat models plus the embedder and reranker is what pushes it into swap.
    escalate_to_stronger_model: bool = Field(default=False, alias="ESCALATE_TO_STRONGER_MODEL")
    chairman_model: str = Field(default="ollama/llama3.2:3b", alias="CHAIRMAN_MODEL")
    # Model that scores answers (faithfulness, relevancy, correctness). Empty = the default
    # generator, which is how this project has always behaved.
    judge_model: str = Field(default="", alias="JUDGE_MODEL")
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
    qdrant_url: str = Field(default="", alias="QDRANT_URL")  # empty: embedded, on disk
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

    # --- Chat run reliability (Fix 1) ---
    # 150s/60s (this project's own suggested starting point) measured too tight on live local
    # hardware: a real timed run on this 16GB-tier machine found individual local-model calls
    # costing ~15-30s each, and a full agentic+summarizer chain needs 6-10+ of them even on the
    # happy path — see docs/DECISIONS.md for the real numbers these were raised against.
    run_timeout_seconds: float = Field(default=240.0, alias="RUN_TIMEOUT_SECONDS")
    run_retry_timeout_seconds: float = Field(default=90.0, alias="RUN_RETRY_TIMEOUT_SECONDS")
    max_llm_calls_per_run: int = Field(default=14, alias="MAX_LLM_CALLS_PER_RUN")
    # How many requests are sent to the local model server at once. Ollama answers one at a
    # time per model by default, so sending more only makes them time out while queued.
    llm_max_concurrency: int = Field(default=1, alias="LLM_MAX_CONCURRENCY")
    ollama_keep_alive: str = Field(default="10m", alias="OLLAMA_KEEP_ALIVE")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def council_model_list(self) -> list[str]:
        return [m.strip() for m in self.council_models.split(",") if m.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
