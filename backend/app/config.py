import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=False)


class Settings(BaseSettings):
    database_url: str | None = None
    github_token: str | None = Field(None, env=["GITHUB_TOKEN", "GITHUB_PAT", "GH_TOKEN"])
    openai_api_key: str | None = None
    openai_model: str | None = None
    cors_origins: str | None = None

    @property
    def github_token_value(self) -> str | None:
        raw = self.github_token
        if raw:
            raw = raw.strip()
            if raw.startswith('"') and raw.endswith('"'):
                raw = raw[1:-1].strip()
            if raw:
                return raw

        for name in ("GITHUB_TOKEN", "GITHUB_PAT", "GH_TOKEN"):
            env_value = os.environ.get(name)
            if env_value:
                env_value = env_value.strip()
                if env_value.startswith('"') and env_value.endswith('"'):
                    env_value = env_value[1:-1].strip()
                if env_value:
                    return env_value

        return None

    worker_poll_seconds: float | None = None

    github_parallel_fetch: int | None = None
    github_use_tarball: bool | None = None
    github_cache_ttl_seconds: int | None = None
    github_cache_dir: str | None = None

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
        origins = (
            self.cors_origins
            or "https://frontend-23d.ny1.zerops.app,http://localhost:5173"
        )

        return [
            origin.strip()
            for origin in origins.split(",")
            if origin.strip()
        ]

    @property
    def worker_poll_seconds_value(self) -> float:
        return self.worker_poll_seconds or 2.0

    @property
    def github_parallel_fetch_value(self) -> int:
        return int(self.github_parallel_fetch or 16)

    @property
    def github_use_tarball_value(self) -> bool:
        if self.github_use_tarball is None:
            return True

        return bool(self.github_use_tarball)

    @property
    def github_cache_ttl_seconds_value(self) -> int:
        return int(self.github_cache_ttl_seconds or 3600)

    @property
    def github_cache_dir_value(self) -> str:
        return self.github_cache_dir or ".cache/snapshots"


@lru_cache
def get_settings() -> Settings:
    return Settings()