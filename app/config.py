from __future__ import annotations

from functools import lru_cache
from os import getenv

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    app_allowed_hosts: str = "localhost,127.0.0.1"
    app_allowed_origins: str = "http://localhost:5173"
    allowed_emails: str = ""
    firebase_project_id: str | None = None
    dev_bypass_auth: bool = False
    scheduler_secret: str | None = None
    github_webhook_secret: str | None = None
    github_token: str | None = None
    github_app_id: str | None = None
    github_app_installation_id: str | None = None
    github_app_private_key: str | None = None
    portfolio_repository: str | None = None
    portfolio_default_branch: str = "main"
    portfolio_content_path: str = "content/writing"
    portfolio_content_format: str = "markdown-frontmatter"
    portfolio_site_url: str = "https://tfinch.dev"
    portfolio_article_url_pattern: str = "/writing/{slug}"
    request_max_bytes: int = Field(default=200_000, ge=1_024, le=2_000_000)

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def email_allowlist(self) -> set[str]:
        return {email.strip().lower() for email in self.allowed_emails.split(",") if email.strip()}

    @property
    def allowed_hosts(self) -> list[str]:
        return [host.strip() for host in self.app_allowed_hosts.split(",") if host.strip()]

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.app_allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
