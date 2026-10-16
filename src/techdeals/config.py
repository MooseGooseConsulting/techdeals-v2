from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
AUTHORIZED_LLM_MODEL = "nvidia/nemotron-3.5-lightning:free"


def require_authorized_llm_model(model: str) -> str:
    """Reject every model except the explicitly authorized free endpoint."""
    if model != AUTHORIZED_LLM_MODEL:
        raise ValueError(
            f"LLM_MODEL must be {AUTHORIZED_LLM_MODEL!r}; paid models and aliases are disabled"
        )
    return model


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    neon_database_url: str
    openrouter_api_key: str = ""
    # Retained for settings compatibility only; these never select the route.
    kilo_gateway_api: str = ""
    kilo_code_api_key: str = ""
    llm_model: str = AUTHORIZED_LLM_MODEL
    llm_batch_size: int = 20
    log_level: str = "INFO"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @field_validator("llm_model")
    @classmethod
    def enforce_free_model(cls, value: str) -> str:
        return require_authorized_llm_model(value)

    @property
    def llm_base_url(self) -> str:
        """Return the LLM API base URL.

        All packaged extraction requests use the authorized OpenRouter endpoint.
        """
        return OPENROUTER_BASE_URL

    @property
    def llm_api_key(self) -> str:
        """Return the LLM API key.

        Use the OpenRouter key only; gateway credentials never route extraction.
        """
        return self.openrouter_api_key


def get_settings() -> Settings:
    return Settings()
