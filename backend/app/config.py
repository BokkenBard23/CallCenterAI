"""Application configuration via pydantic-settings."""

from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralised application settings.

    Values are loaded from environment variables or a .env file.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    debug: bool = True

    # ── CORS ──
    cors_origins: List[str] = ["http://localhost:5173", "http://localhost:3000"]

    # ── Paths ──
    transcrib_dir: Path = Path("../Transcrib")
    smartlogger_dir: Path = Path("../Transcrib/smartlogger")
    data_dir: Path = Path("../data")

    # ── LLM: Ollama ──
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"

    # ── LLM: YandexGPT ──
    yandexgpt_api_key: str = ""
    yandexgpt_folder_id: str = ""
    yandexgpt_model: str = "yandexgpt-lite"

    # ── LLM: GigaChat ──
    gigachat_auth_key: str = ""
    gigachat_scope: str = "GIGACHAT_API_PERS"

    # ── LLM: Beeline AI (GLM family) ──
    # Model codes per official Beeline AI docs (https://docs.ai.beeline.ru/quickstart/models/).
    # Family codes are lowercase slugs sent in the `model` field of
    # POST /api/v3/chat/completions.
    beeline_api_key: str = ""
    beeline_default_model: str = "glm-xlarge"  # GLM-5.2 family, serious tasks (summary, quality, dict_analysis, restructured)
    beeline_fast_model: str = "glm-xlarge-fast"  # GLM-5.2 fast, short classifications (shares GLM slots)
    # ── LLM: Qwen family via Beeline AI (OpenAI-compatible endpoint) ──
    # Current primary codes (Qwen3.6-27B Dense family — PRIMARY since 2026-07-14):
    #   qwen-medium-dense       — Qwen3.6-27B Dense (text-only, 262K context, 6 slots) ✅ PRIMARY
    #   qwen-medium-dense-fast  — Qwen3.6-27B Dense fast (no reasoning, 6 slots) ✅ CLASSIFICATION
    #
    # Legacy fallback codes (Qwen3.5-35B — FALLBACK):
    #   qwen-medium            — Qwen3.5-35B (262K context, 3 slots) — FALLBACK
    #   qwen-medium-fast       — Qwen3.5-35B fast — FALLBACK
    #
    # ⚠️ DEPRECATED (do NOT use — limited context ~47.8K, scheduled for removal 2026-07-27):
    #   qwen-medium-preview / qwen-medium-preview-fast (Qwen3.6-35B preview)
    #
    # Auxiliary model:
    #   coding-medium          — Coding-focused model (used by dict_ai structured output)
    #
    # Context window: 262K tokens (verified for qwen-medium, qwen-medium-dense)
    # Parallelism: 6 slots per Qwen3.6 Dense model (per Beeline AI /me/limits API)
    qwen35_model: str = "qwen-medium"                  # Qwen3.5-35B (FALLBACK, 262K context)
    qwen35_fast_model: str = "qwen-medium-fast"        # Qwen3.5-35B fast (FALLBACK)
    qwen36_model: str = "qwen-medium-dense"            # Qwen3.6-27B Dense ✅ PRIMARY (6 slots)
    qwen36_fast_model: str = "qwen-medium-dense-fast"   # Qwen3.6-27B Dense fast ✅ CLASSIFICATION (6 slots)
    coding_model: str = "coding-medium"                # Coding-focused model (for dict_ai structured output)

    # ── Per-provider parallelism (asyncio.Semaphore sizes) ──
    # Total max parallel = 2 (GLM, FALLBACK) + 3 (Qwen3.5, FALLBACK) +
    #                       6 (qwen-medium-dense, PRIMARY) + 6 (qwen-medium-dense-fast, CLASSIFICATION) = 17
    # NOTE: actual concurrent limits are also exposed dynamically via
    # GET /api/v3/me/limits?model={publicModelName} (see app.services.llm_limits).
    # These values are fallback defaults used when the limits API is unreachable.
    glm_max_concurrent: int = 2      # shared between glm-xlarge and glm-xlarge-fast (FALLBACK)
    qwen35_max_concurrent: int = 3    # Qwen3.5 (FALLBACK)
    qwen36_max_concurrent: int = 6    # qwen-medium-dense ✅ 6 parallel slots (was 3)

    # ── Embeddings: FRIDA (Beeline AI) ──
    # FRIDA embeddings endpoint: /api/v2/embeddings (verified 2026-07-18).
    # /api/v3/embeddings returns 404 — do NOT use v3.
    frida_base_url: str = "https://api.ai.beeline.ru/api/v2"
    frida_model: str = "frida"
    frida_dimensions: int = 1536
    frida_max_context_tokens: int = 500
    frida_batch_size: int = 10

    # ── Vector Store ──
    vector_store_dimension: int = 1536
    vector_store_index_dir: Path = Path("data/vector_store")
    vector_store_auto_save: bool = True

    # ── Hybrid Search ──
    hybrid_search_rrf_k: int = 60
    hybrid_search_ner_boost_per_match: float = 0.1
    hybrid_search_ner_per_weight: float = 1.5
    hybrid_search_default_top_k: int = 10

    # ── Circuit Breaker: LLM providers ──
    llm_circuit_breaker_failures: int = 3
    llm_circuit_breaker_reset_seconds: float = 60.0

    # ── Search fallback ──
    search_fallback_enabled: bool = True

    # ── LLM Orchestrator (IP-3.6) ──
    llm_orchestrator_steps: List[str] = ["sentiment", "conflict", "profanity", "topic"]
    llm_orchestrator_enabled: bool = True
    # Parallel mode: run all analysis steps concurrently via asyncio.gather.
    # Each step respects its provider's semaphore, so the 8-slot budget is honoured.
    llm_orchestrator_parallel: bool = True

    # ── Domain-specific analysis (IP-6.1) ──
    analysis_default_domain: str = "general"

    # ── Session persistence ──
    session_backend: str = "sqlite"  # "memory" | "sqlite" (future: "postgresql")
    session_db_path: Path = Path("data/sessions.db")
    session_ttl_seconds: int = 7200  # 2 hours

    # ── Upload limits ──
    max_upload_size_mb: int = 50

    # ── Health check ──
    health_check_enabled: bool = True
    app_version: str = "1.0.0"

    # ── PII Masking (ID-4) ──
    pii_masking_enabled: bool = True
    pii_masking_language: str = "ru"
    pii_masking_min_score: float = 0.5
    pii_masking_circuit_reset_seconds: float = 60.0
    pii_masking_failure_threshold: int = 3

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024


settings = Settings()
