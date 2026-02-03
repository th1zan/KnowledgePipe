"""Audio uploader module.

This module provides uploaders for storing podcast audio files
to various backends: local filesystem, Backblaze B2, etc.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3
import structlog
from botocore.config import Config

from src.config import get_settings

logger = structlog.get_logger()


class AudioUploader(ABC):
    """Abstract base class for audio uploaders."""

    @abstractmethod
    def upload(self, audio_data: bytes, filename: str) -> str:
        """Upload audio data and return public URL.

        Args:
            audio_data: Raw audio bytes.
            filename: Desired filename for the audio.

        Returns:
            Public URL where the audio can be accessed.

        Raises:
            Exception: If upload fails.
        """
        pass

    @abstractmethod
    def delete(self, filename: str) -> bool:
        """Delete an uploaded audio file.

        Args:
            filename: Name of the file to delete.

        Returns:
            True if deleted successfully, False otherwise.
        """
        pass

    @abstractmethod
    def health_check(self) -> bool:
        """Check if the uploader is working.

        Returns:
            True if healthy, False otherwise.
        """
        pass


class LocalUploader(AudioUploader):
    """Upload audio files to local filesystem."""

    def __init__(self, local_path: str | None = None, public_url: str | None = None):
        """Initialize local uploader.

        Args:
            local_path: Local directory path for storing files.
            public_url: Base URL for accessing files publicly.
        """
        settings = get_settings()
        self.local_path = Path(local_path or settings.audio_local_path)
        self.public_url = (public_url or settings.audio_public_url).rstrip("/")

        # Try to ensure directory exists (may fail if path is invalid)
        try:
            self.local_path.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass  # Will be caught by health_check or upload

    def upload(self, audio_data: bytes, filename: str) -> str:
        """Upload audio to local filesystem.

        Args:
            audio_data: Raw audio bytes.
            filename: Desired filename.

        Returns:
            Public URL for the audio file.
        """
        filepath = self.local_path / filename

        with open(filepath, "wb") as f:
            f.write(audio_data)

        public_url = f"{self.public_url}/{filename}"

        logger.info(
            "audio_uploaded_locally",
            filename=filename,
            size=len(audio_data),
            path=str(filepath),
        )

        return public_url

    def delete(self, filename: str) -> bool:
        """Delete a local audio file.

        Args:
            filename: Name of the file to delete.

        Returns:
            True if deleted, False otherwise.
        """
        filepath = self.local_path / filename

        try:
            if filepath.exists():
                filepath.unlink()
                logger.info("audio_deleted_locally", filename=filename)
                return True
            return False
        except Exception as e:
            logger.error("audio_delete_failed", filename=filename, error=str(e))
            return False

    def health_check(self) -> bool:
        """Check if local storage is accessible.

        Returns:
            True if directory is writable.
        """
        try:
            test_file = self.local_path / ".health_check"
            test_file.write_text("ok")
            test_file.unlink()
            return True
        except Exception:
            return False


class BackblazeUploader(AudioUploader):
    """Upload audio files to Backblaze B2 (S3 compatible)."""

    def __init__(
        self,
        key_id: str | None = None,
        application_key: str | None = None,
        bucket: str | None = None,
        endpoint: str | None = None,
    ):
        """Initialize Backblaze uploader.

        Args:
            key_id: Backblaze key ID.
            application_key: Backblaze application key.
            bucket: Bucket name.
            endpoint: S3-compatible endpoint URL.
        """
        settings = get_settings()

        self.key_id = key_id or settings.backblaze_key_id
        self.application_key = application_key or settings.backblaze_application_key
        self.bucket = bucket or settings.backblaze_bucket
        self.endpoint = endpoint or settings.backblaze_endpoint

        # Initialize S3 client
        self._client = None

    @property
    def client(self):
        """Lazy-load S3 client."""
        if self._client is None:
            self._client = boto3.client(
                "s3",
                endpoint_url=self.endpoint,
                aws_access_key_id=self.key_id,
                aws_secret_access_key=self.application_key,
                config=Config(signature_version="s3v4"),
            )
        return self._client

    def upload(self, audio_data: bytes, filename: str) -> str:
        """Upload audio to Backblaze B2.

        Args:
            audio_data: Raw audio bytes.
            filename: Desired filename.

        Returns:
            Public URL for the audio file.
        """
        # Add timestamp prefix for uniqueness
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        key = f"podcasts/{timestamp}/{filename}"

        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=audio_data,
            ContentType="audio/mpeg",
            ACL="public-read",
        )

        # Construct public URL
        # Backblaze B2 public URLs follow this pattern
        public_url = f"{self.endpoint}/{self.bucket}/{key}"

        logger.info(
            "audio_uploaded_backblaze",
            filename=filename,
            size=len(audio_data),
            key=key,
        )

        return public_url

    def delete(self, filename: str) -> bool:
        """Delete a file from Backblaze B2.

        Args:
            filename: Name/key of the file to delete.

        Returns:
            True if deleted, False otherwise.
        """
        try:
            self.client.delete_object(Bucket=self.bucket, Key=filename)
            logger.info("audio_deleted_backblaze", filename=filename)
            return True
        except Exception as e:
            logger.error("audio_delete_failed", filename=filename, error=str(e))
            return False

    def health_check(self) -> bool:
        """Check if Backblaze B2 is accessible.

        Returns:
            True if bucket is accessible.
        """
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return True
        except Exception:
            return False


def get_uploader() -> AudioUploader:
    """Factory function to get the configured uploader.

    Returns:
        AudioUploader instance based on configuration.

    Raises:
        ValueError: If configured hosting type is not supported.
    """
    settings = get_settings()
    hosting = settings.audio_hosting.lower()

    if hosting == "local":
        return LocalUploader()
    elif hosting == "backblaze":
        return BackblazeUploader()
    else:
        raise ValueError(f"Unsupported audio hosting type: {hosting}")


def upload_episode(episode_id: str, audio_data: bytes) -> str:
    """Upload a podcast episode audio file.

    Args:
        episode_id: ID of the episode.
        audio_data: Raw audio bytes.

    Returns:
        Public URL where the audio can be accessed.
    """
    # Generate filename
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    # Clean episode_id for filename
    safe_id = episode_id.replace(":", "_").replace("/", "_")
    filename = f"{safe_id}_{timestamp}.mp3"

    uploader = get_uploader()
    public_url = uploader.upload(audio_data, filename)

    logger.info(
        "episode_uploaded",
        episode_id=episode_id,
        filename=filename,
        public_url=public_url,
    )

    return public_url
