"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta
from typing import Mapping

SUPPORTED_IMPORT_MODES = ("daily", "full")


class ConfigurationError(RuntimeError):
    """Raised when the application is misconfigured."""


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name)
    if not value:
        raise ConfigurationError(
            f"Missing required environment variable: {name}"
        )
    return value


@dataclass(frozen=True)
class InaturalistSettings:
    """Connection settings for the iNaturalist API."""

    site_url: str
    api_url: str
    project_id: int
    per_page: int
    username: str
    password: str
    client_id: str
    client_secret: str


@dataclass(frozen=True)
class GbifSettings:
    """Connection settings for the GBIF API."""

    api_url: str
    request_delay: float


@dataclass(frozen=True)
class DatabaseSettings:
    """PostgreSQL connection settings."""

    url: str


@dataclass(frozen=True)
class Settings:
    """Top-level application settings."""

    import_mode: str
    log_level: str
    user_agent: str
    request_delay: float
    daily_overlap: timedelta
    database: DatabaseSettings
    inaturalist: InaturalistSettings
    gbif: GbifSettings

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        """Build settings from the environment (or a supplied mapping)."""
        env = os.environ if env is None else env

        import_mode = env.get("IMPORT_MODE", "daily")
        if import_mode not in SUPPORTED_IMPORT_MODES:
            raise ConfigurationError(
                "IMPORT_MODE must be one of "
                f"{SUPPORTED_IMPORT_MODES}, got {import_mode!r}"
            )

        return cls(
            import_mode=import_mode,
            log_level=env.get("LOG_LEVEL", "INFO"),
            user_agent=env.get(
                "USER_AGENT", "pladias-inaturalist-importer/1.0"
            ),
            request_delay=float(env.get("REQUEST_DELAY", "1")),
            # Daily import deliberately overlaps the previous period.
            # This makes the import robust against timestamps and
            # interrupted runs.
            daily_overlap=timedelta(days=3),
            database=DatabaseSettings(
                url=_required(env, "DATABASE_URL"),
            ),
            inaturalist=InaturalistSettings(
                site_url=env.get(
                    "INAT_SITE_URL", "https://www.inaturalist.org"
                ),
                api_url=env.get(
                    "INAT_API_URL", "https://api.inaturalist.org/v2"
                ),
                project_id=int(env.get("INAT_PROJECT_ID", "183334")),
                per_page=int(env.get("INAT_PER_PAGE", "1000")),
                username=_required(env, "INAT_USERNAME"),
                password=_required(env, "INAT_PASSWORD"),
                client_id=_required(env, "INAT_CLIENT_ID"),
                client_secret=_required(env, "INAT_CLIENT_SECRET"),
            ),
            gbif=GbifSettings(
                api_url=env.get(
                    "GBIF_API_URL", "https://api.gbif.org/v1"
                ),
                request_delay=float(
                    env.get("GBIF_REQUEST_DELAY", "0.2")
                ),
            ),
        )
