from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str | None = None
    github_token: str | None = None
    openai_api_key: str | None = None
    openai_model: str | None = None
    cors_origins: str | None = None
    worker_poll_seconds: float | None = None
    github_parallel_fetch: int | None = None
    github_use_tarball: bool | None = None
    github_cache_ttl_seconds: int | None = None
    github_cache_dir: str | None = None
    github_cache_ttl_seconds: int | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def database_url_or_default(self) -> str:
        return self.database_url or "sqlite:///./infrapilot.db"

    @property
    def cors_origin_list(self) -> list[str]:
        origins = self.cors_origins or "http://localhost:5173"
        return [x.strip() for x in origins.split(",") if x.strip()]

    @property
    def worker_poll_seconds_value(self) -> float:
        return self.worker_poll_seconds or 2.0

    @property
    def github_parallel_fetch_value(self) -> int:
        return int(self.github_parallel_fetch or 16)

    @property
    def github_use_tarball_value(self) -> bool:
        # Prefer tarball by default for faster snapshots on public repos
        if self.github_use_tarball is None:
            return True
        return bool(self.github_use_tarball)

    @property
    def github_cache_ttl_seconds_value(self) -> int:
        # default 1 hour
        return int(self.github_cache_ttl_seconds or 3600)

    @property
    def github_cache_dir_value(self) -> str:
        return self.github_cache_dir or ".cache/snapshots"


@lru_cache
def get_settings() -> Settings:
    return Settings()
