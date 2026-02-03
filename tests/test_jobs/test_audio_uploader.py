"""Tests for the audio uploader module."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.jobs.audio_uploader import (
    AudioUploader,
    BackblazeUploader,
    LocalUploader,
    get_uploader,
    upload_episode,
)


class TestLocalUploader:
    """Tests for LocalUploader class."""

    def test_upload_creates_file(self):
        """Test that upload creates file on disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            uploader = LocalUploader(
                local_path=tmpdir,
                public_url="https://example.com/audio",
            )

            audio_data = b"fake audio content"
            url = uploader.upload(audio_data, "test.mp3")

            assert url == "https://example.com/audio/test.mp3"
            assert (Path(tmpdir) / "test.mp3").exists()
            assert (Path(tmpdir) / "test.mp3").read_bytes() == audio_data

    def test_upload_strips_trailing_slash(self):
        """Test that trailing slash is handled correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            uploader = LocalUploader(
                local_path=tmpdir,
                public_url="https://example.com/audio/",
            )

            url = uploader.upload(b"content", "test.mp3")

            assert url == "https://example.com/audio/test.mp3"

    def test_delete_existing_file(self):
        """Test deleting an existing file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            uploader = LocalUploader(
                local_path=tmpdir, public_url="https://example.com"
            )

            # Create file first
            filepath = Path(tmpdir) / "test.mp3"
            filepath.write_bytes(b"content")

            result = uploader.delete("test.mp3")

            assert result is True
            assert not filepath.exists()

    def test_delete_nonexistent_file(self):
        """Test deleting a non-existent file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            uploader = LocalUploader(
                local_path=tmpdir, public_url="https://example.com"
            )

            result = uploader.delete("nonexistent.mp3")

            assert result is False

    def test_health_check_success(self):
        """Test health check with writable directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            uploader = LocalUploader(
                local_path=tmpdir, public_url="https://example.com"
            )

            result = uploader.health_check()

            assert result is True

    def test_health_check_failure(self):
        """Test health check with non-writable directory."""
        uploader = LocalUploader(
            local_path="/nonexistent/path/that/does/not/exist",
            public_url="https://example.com",
        )

        result = uploader.health_check()

        assert result is False

    def test_creates_directory_if_not_exists(self):
        """Test that uploader creates directory if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            new_path = Path(tmpdir) / "new" / "nested" / "dir"

            uploader = LocalUploader(
                local_path=str(new_path),
                public_url="https://example.com",
            )

            assert new_path.exists()


class TestBackblazeUploader:
    """Tests for BackblazeUploader class."""

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings for Backblaze."""
        with patch("src.jobs.audio_uploader.get_settings") as mock:
            mock.return_value.backblaze_key_id = "key-id"
            mock.return_value.backblaze_application_key = "app-key"
            mock.return_value.backblaze_bucket = "test-bucket"
            mock.return_value.backblaze_endpoint = "https://s3.example.com"
            yield mock

    def test_upload_success(self, mock_settings):
        """Test successful upload to Backblaze."""
        uploader = BackblazeUploader()

        with patch.object(uploader, "_client") as mock_client:
            mock_client.put_object = MagicMock()

            url = uploader.upload(b"audio content", "episode.mp3")

            mock_client.put_object.assert_called_once()
            call_kwargs = mock_client.put_object.call_args[1]
            assert call_kwargs["Bucket"] == "test-bucket"
            assert call_kwargs["Body"] == b"audio content"
            assert call_kwargs["ContentType"] == "audio/mpeg"
            assert "episode.mp3" in call_kwargs["Key"]

    def test_delete_success(self, mock_settings):
        """Test successful delete from Backblaze."""
        uploader = BackblazeUploader()

        with patch.object(uploader, "_client") as mock_client:
            mock_client.delete_object = MagicMock()

            result = uploader.delete("podcasts/20240115/episode.mp3")

            assert result is True
            mock_client.delete_object.assert_called_once()

    def test_delete_failure(self, mock_settings):
        """Test handling delete failure."""
        uploader = BackblazeUploader()

        with patch.object(uploader, "_client") as mock_client:
            mock_client.delete_object.side_effect = Exception("API Error")

            result = uploader.delete("test.mp3")

            assert result is False

    def test_health_check_success(self, mock_settings):
        """Test health check when bucket is accessible."""
        uploader = BackblazeUploader()

        with patch.object(uploader, "_client") as mock_client:
            mock_client.head_bucket = MagicMock()

            result = uploader.health_check()

            assert result is True

    def test_health_check_failure(self, mock_settings):
        """Test health check when bucket is not accessible."""
        uploader = BackblazeUploader()

        with patch.object(uploader, "_client") as mock_client:
            mock_client.head_bucket.side_effect = Exception("Access Denied")

            result = uploader.health_check()

            assert result is False


class TestGetUploader:
    """Tests for get_uploader factory function."""

    def test_get_uploader_local(self):
        """Test getting local uploader."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("src.jobs.audio_uploader.get_settings") as mock_settings:
                mock_settings.return_value.audio_hosting = "local"
                mock_settings.return_value.audio_local_path = tmpdir
                mock_settings.return_value.audio_public_url = "https://example.com"

                uploader = get_uploader()

                assert isinstance(uploader, LocalUploader)

    def test_get_uploader_backblaze(self):
        """Test getting Backblaze uploader."""
        with patch("src.jobs.audio_uploader.get_settings") as mock_settings:
            mock_settings.return_value.audio_hosting = "backblaze"
            mock_settings.return_value.backblaze_key_id = "key"
            mock_settings.return_value.backblaze_application_key = "secret"
            mock_settings.return_value.backblaze_bucket = "bucket"
            mock_settings.return_value.backblaze_endpoint = "https://s3.example.com"

            uploader = get_uploader()

            assert isinstance(uploader, BackblazeUploader)

    def test_get_uploader_case_insensitive(self):
        """Test that hosting type is case-insensitive."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("src.jobs.audio_uploader.get_settings") as mock_settings:
                mock_settings.return_value.audio_hosting = "LOCAL"
                mock_settings.return_value.audio_local_path = tmpdir
                mock_settings.return_value.audio_public_url = "https://example.com"

                uploader = get_uploader()

                assert isinstance(uploader, LocalUploader)

    def test_get_uploader_unsupported(self):
        """Test that unsupported hosting type raises error."""
        with patch("src.jobs.audio_uploader.get_settings") as mock_settings:
            mock_settings.return_value.audio_hosting = "unsupported"

            with pytest.raises(ValueError, match="Unsupported"):
                get_uploader()


class TestUploadEpisode:
    """Tests for upload_episode function."""

    def test_upload_episode_success(self):
        """Test successful episode upload."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("src.jobs.audio_uploader.get_settings") as mock_settings:
                mock_settings.return_value.audio_hosting = "local"
                mock_settings.return_value.audio_local_path = tmpdir
                mock_settings.return_value.audio_public_url = "https://cdn.example.com"

                url = upload_episode("episode:123", b"audio data")

                assert "https://cdn.example.com" in url
                assert "episode_123" in url
                assert ".mp3" in url

                # Verify file was created
                files = list(Path(tmpdir).glob("*.mp3"))
                assert len(files) == 1

    def test_upload_episode_sanitizes_id(self):
        """Test that episode ID is sanitized for filename."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("src.jobs.audio_uploader.get_settings") as mock_settings:
                mock_settings.return_value.audio_hosting = "local"
                mock_settings.return_value.audio_local_path = tmpdir
                mock_settings.return_value.audio_public_url = "https://cdn.example.com"

                url = upload_episode("podcast_episode:abc/def", b"audio")

                # Colons and slashes should be replaced with underscores
                assert "podcast_episode_abc_def" in url
