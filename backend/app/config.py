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

    # ── LLM: Beeline AI ──
    beeline_api_key: str = ""
    beeline_default_model: str = "glm-5.1"

    # ── Embeddings: FRIDA (Beeline AI) ──
    frida_base_url: str = "https://api.ai.beeline.ru/api/v3"
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

    # ── Upload limits ──
    max_upload_size_mb: int = 50

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024


settings = Settings()
