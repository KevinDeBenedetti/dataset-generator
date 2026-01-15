from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with Pydantic validation and .env support."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # API Configuration
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"

    # CORS - configurable origins for security
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:8080"]

    # Scraping
    max_retries: int = 3
    timeout: int = 10
    scrape_delay: float = 0.2

    # LLM
    max_tokens_cleaning: int = 3000
    max_tokens_qa: int = 4000
    temperature: float = 0.0

    # Available LLMs (comma-separated in env)
    available_models: list[str] = [
        "mistral-small-3.1-24b-instruct-2503",
        "gpt-4-0613",
        "gpt-3.5-turbo-1106",
    ]

    # Defaults for runtime overrides
    target_language: str = "en"
    model_cleaning: str = "mistral-small-3.1-24b-instruct-2503"
    model_qa: str = "mistral-small-3.1-24b-instruct-2503"

    # Output
    output_formats: list[str] = ["json", "jsonl", "csv"]
    scrapes_dir: str = "scrapes"
    datasets_dir: str = "datasets"

    @field_validator("available_models", "cors_origins", mode="before")
    @classmethod
    def parse_comma_separated(cls, v):
        """Parse comma-separated string into list."""
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    @model_validator(mode="after")
    def ensure_models_in_available(self):
        """Ensure default models are in available models list."""
        if self.model_cleaning not in self.available_models:
            self.available_models.append(self.model_cleaning)
        if self.model_qa not in self.available_models:
            self.available_models.append(self.model_qa)
        return self


config = Settings()


# Backwards compatibility alias
Config = Settings
