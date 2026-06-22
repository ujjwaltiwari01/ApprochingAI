from functools import lru_cache
import os
import re

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = Field(default="postgresql+asyncpg://localhost/test", alias="DATABASE_URL")

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        url = value.strip().strip('"').strip("'")
        if url.startswith("postgresql://") and "+asyncpg" not in url:
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

        pooler_host = os.getenv("SUPABASE_POOLER_HOST", "").strip()
        if pooler_host:
            match = re.search(
                r"^postgresql\+asyncpg://postgres:([^@]+)@db\.([^.]+)\.supabase\.co:5432/(.+)$",
                url,
            )
            if match:
                password, project_ref, dbname = match.groups()
                url = (
                    f"postgresql+asyncpg://postgres.{project_ref}:{password}"
                    f"@{pooler_host}:5432/{dbname}"
                )
        return url

    supabase_url: str = Field(default="", alias="SUPABASE_URL")
    supabase_service_role_key: str = Field(default="", alias="SUPABASE_SERVICE_ROLE_KEY")

    render_public_url: str = Field(default="", alias="RENDER_PUBLIC_URL")
    webhook_secret: str = Field(default="", alias="WEBHOOK_SECRET")
    job_secret: str = Field(default="", alias="JOB_SECRET")

    brevo_api_key_1: str = Field(default="", alias="BREVO_API_KEY_1")
    brevo_sender_email_1: str = Field(default="", alias="BREVO_SENDER_EMAIL_1")
    brevo_sender_name_1: str = Field(default="Ujjwal Tiwari", alias="BREVO_SENDER_NAME_1")
    brevo_api_key_2: str = Field(default="", alias="BREVO_API_KEY_2")
    brevo_sender_email_2: str = Field(default="", alias="BREVO_SENDER_EMAIL_2")
    brevo_sender_name_2: str = Field(default="Ujjwal Tiwari", alias="BREVO_SENDER_NAME_2")
    brevo_api_key_3: str = Field(default="", alias="BREVO_API_KEY_3")
    brevo_sender_email_3: str = Field(default="", alias="BREVO_SENDER_EMAIL_3")
    brevo_sender_name_3: str = Field(default="Ujjwal Tiwari", alias="BREVO_SENDER_NAME_3")

    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    openrouter_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    cerebras_api_key: str = Field(default="", alias="CEREBRAS_API_KEY")
    mistral_api_key: str = Field(default="", alias="MISTRAL_API_KEY")
    mistral_api_key_2: str = Field(default="", alias="MISTRAL_API_KEY_2")

    sender_portfolio_url: str = Field(
        default="https://ujjwaltiwari01.netlify.app/", alias="SENDER_PORTFOLIO_URL"
    )
    sender_linkedin_url: str = Field(
        default="https://linkedin.com/in/ujjwal-tiwari-b34044341", alias="SENDER_LINKEDIN_URL"
    )
    sender_resume_url: str = Field(default="", alias="SENDER_RESUME_URL")
    sender_email: str = Field(default="ujjwal.it2023-24@recabn.ac.in", alias="SENDER_EMAIL")

    daily_new_per_account: int = Field(default=150, alias="DAILY_NEW_PER_ACCOUNT")
    daily_followup_per_account: int = Field(default=150, alias="DAILY_FOLLOWUP_PER_ACCOUNT")
    llm_timeout_seconds: int = Field(default=30, alias="LLM_TIMEOUT_SECONDS")
    llm_providers: str = Field(
        default="mistral,cerebras,openrouter,gemini,groq",
        alias="LLM_PROVIDERS",
    )
    llm_request_delay_ms: int = Field(default=400, alias="LLM_REQUEST_DELAY_MS")
    llm_max_concurrent: int = Field(default=2, alias="LLM_MAX_CONCURRENT")
    llm_email_max_retries: int = Field(default=1, alias="LLM_EMAIL_MAX_RETRIES")
    llm_compact_analysis: bool = Field(default=True, alias="LLM_COMPACT_ANALYSIS")
    job_chunk_size: int = Field(default=15, alias="JOB_CHUNK_SIZE")
    skip_playwright: bool = Field(default=True, alias="SKIP_PLAYWRIGHT")
    allow_invalid_send: bool = Field(default=False, alias="ALLOW_INVALID_SEND")
    cache_ttl_days: int = Field(default=30, alias="CACHE_TTL_DAYS")
    batch_size: int = Field(default=100, alias="BATCH_SIZE")
    playwright_concurrency: int = Field(default=3, alias="PLAYWRIGHT_CONCURRENCY")

    @property
    def brevo_accounts(self) -> list[dict]:
        accounts = []
        for i in range(1, 4):
            accounts.append(
                {
                    "id": i,
                    "api_key": getattr(self, f"brevo_api_key_{i}"),
                    "sender_email": getattr(self, f"brevo_sender_email_{i}"),
                    "sender_name": getattr(self, f"brevo_sender_name_{i}"),
                    "daily_new": self.daily_new_per_account,
                    "daily_followup": self.daily_followup_per_account,
                }
            )
        return accounts

    @property
    def mistral_api_keys(self) -> list[str]:
        keys = []
        for key in (self.mistral_api_key, self.mistral_api_key_2):
            if key and key.strip():
                keys.append(key.strip())
        return keys


@lru_cache
def get_settings() -> Settings:
    return Settings()
