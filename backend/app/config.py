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

    # ── Upload limits ──
    max_upload_size_mb: int = 50

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024


settings = Settings()
