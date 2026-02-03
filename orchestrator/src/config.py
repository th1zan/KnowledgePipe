"""Configuration settings for the orchestrator."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Readeck
    readeck_url: str = "http://readeck:8000"
    readeck_token: str = ""

    # Open Notebook
    open_notebook_url: str = "http://open-notebook-backend:5055"
    open_notebook_password: str = ""

    # RSS Feeds
    rss_feeds: str = ""

    # Scheduler
    rss_fetch_hour: int = 8
    sync_day: str = "sunday"
    sync_hour: int = 23

    # Audio hosting
    audio_hosting: str = "local"  # local | backblaze | anchor
    audio_local_path: str = "/audio"
    audio_public_url: str = "http://localhost/audio"

    # Backblaze B2
    backblaze_key_id: str = ""
    backblaze_application_key: str = ""
    backblaze_bucket: str = "weekly-digest-audio"
    backblaze_endpoint: str = "https://s3.us-west-000.backblazeb2.com"

    # Podcast profiles
    podcast_episode_profile: str = "default"
    podcast_speaker_profile: str = "default"

    # Database
    database_path: str = "/data/state.db"

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"  # json | console

    # API
    api_port: int = 8002
    api_debug: bool = False

    # Timeouts (seconds)
    source_processing_timeout: int = 300
    podcast_generation_timeout: int = 600
    http_timeout: int = 30

    # Retry
    max_retries: int = 3
    retry_delay: int = 5

    @property
    def rss_feed_list(self) -> list[str]:
        """Parse RSS feeds from comma-separated string."""
        if not self.rss_feeds:
            return []
        return [feed.strip() for feed in self.rss_feeds.split(",") if feed.strip()]


# Global settings instance
_settings: Settings | None = None


def get_settings() -> Settings:
    """Get the global settings instance.

    Returns:
        Settings instance, created if it doesn't exist.
    """
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Reset the global settings instance.

    This is primarily useful for testing.
    """
    global _settings
    _settings = None


# Backwards compatibility alias
settings = get_settings()
