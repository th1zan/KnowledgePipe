"""Tests for the RSS feeds API."""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from src.api.feeds import (
    _get_cached_feed,
    _set_cached_feed,
    generate_podcast_feed,
    generate_reviews_feed,
    invalidate_cache,
    router,
)
from src.database import (
    Base,
    Episode,
    SyncLog,
    add_episode,
    create_sync_log,
    get_session,
    mark_episode_uploaded,
    reset_engine,
    set_engine,
    update_sync_log,
)

# Create a minimal FastAPI app for testing
from fastapi import FastAPI

app = FastAPI()
app.include_router(router)
client = TestClient(app)


@pytest.fixture
def temp_db():
    """Create a temporary database for testing.

    Yields:
        Path to the temporary database file.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        engine = create_engine(
            f"sqlite:///{db_path}",
            echo=False,
            connect_args={"check_same_thread": False},
        )
        set_engine(engine)
        Base.metadata.create_all(engine)
        # Clear cache before each test
        invalidate_cache()
        yield db_path
        reset_engine()


@pytest.fixture
def sample_episodes(temp_db: Path):
    """Create sample episodes for testing."""
    episodes = []
    for i in range(3):
        ep = add_episode(
            notebook_id=f"notebook:{i}",
            episode_id=f"episode:{i}",
            episode_name=f"Week {i + 1}",
            audio_url=f"/api/podcasts/episodes/{i}/audio",
        )
        # Mark as uploaded
        mark_episode_uploaded(
            episode_id=f"episode:{i}",
            public_url=f"https://cdn.example.com/episode-{i}.mp3",
        )
        episodes.append(ep)
    return episodes


@pytest.fixture
def sample_sync_logs(temp_db: Path):
    """Create sample sync logs for testing."""
    logs = []
    for i in range(3):
        log = create_sync_log(
            notebook_id=f"notebook:{i}",
            bookmarks_count=10 + i,
        )
        update_sync_log(log.id, status="completed")
        logs.append(log)
    return logs


class TestCaching:
    """Tests for feed caching."""

    def test_set_and_get_cached_feed(self, temp_db: Path):
        """Test setting and getting cached feed."""
        _set_cached_feed("test", "<rss>content</rss>")

        result = _get_cached_feed("test")
        assert result == "<rss>content</rss>"

    def test_get_cached_feed_not_found(self, temp_db: Path):
        """Test getting non-existent cached feed."""
        result = _get_cached_feed("nonexistent")
        assert result is None

    def test_invalidate_cache(self, temp_db: Path):
        """Test cache invalidation."""
        _set_cached_feed("test1", "content1")
        _set_cached_feed("test2", "content2")

        invalidate_cache()

        assert _get_cached_feed("test1") is None
        assert _get_cached_feed("test2") is None


class TestGeneratePodcastFeed:
    """Tests for podcast feed generation."""

    def test_generate_podcast_feed_empty(self, temp_db: Path):
        """Test generating podcast feed with no episodes."""
        with patch("src.api.feeds.get_settings") as mock_settings:
            mock_settings.return_value.audio_public_url = "https://example.com/audio"

            content = generate_podcast_feed()

        assert "<?xml" in content
        assert "<rss" in content
        assert "Weekly Digest Podcast" in content
        # Validate XML
        ElementTree.fromstring(content)

    def test_generate_podcast_feed_with_episodes(
        self, temp_db: Path, sample_episodes: list
    ):
        """Test generating podcast feed with episodes."""
        with patch("src.api.feeds.get_settings") as mock_settings:
            mock_settings.return_value.audio_public_url = "https://example.com/audio"

            content = generate_podcast_feed()

        assert "Week 1" in content
        assert "Week 2" in content
        assert "Week 3" in content
        assert "https://cdn.example.com/episode-0.mp3" in content

        # Validate XML
        root = ElementTree.fromstring(content)
        items = root.findall(".//item")
        assert len(items) == 3

    def test_generate_podcast_feed_itunes_tags(
        self, temp_db: Path, sample_episodes: list
    ):
        """Test that iTunes tags are present."""
        with patch("src.api.feeds.get_settings") as mock_settings:
            mock_settings.return_value.audio_public_url = "https://example.com/audio"

            content = generate_podcast_feed()

        # Check for iTunes namespace content
        assert "itunes" in content.lower() or "podcast" in content.lower()

    def test_generate_podcast_feed_caching(self, temp_db: Path, sample_episodes: list):
        """Test that feed is cached after generation."""
        with patch("src.api.feeds.get_settings") as mock_settings:
            mock_settings.return_value.audio_public_url = "https://example.com/audio"

            # First call generates
            content1 = generate_podcast_feed()

            # Should be cached now
            cached = _get_cached_feed("podcast")
            assert cached is not None
            assert cached == content1


class TestGenerateReviewsFeed:
    """Tests for reviews feed generation."""

    def test_generate_reviews_feed_empty(self, temp_db: Path):
        """Test generating reviews feed with no logs."""
        with patch("src.api.feeds.get_settings") as mock_settings:
            mock_settings.return_value.audio_public_url = "https://example.com"

            content = generate_reviews_feed()

        assert "<?xml" in content
        assert "<rss" in content
        assert "Weekly Digest Reviews" in content
        # Validate XML
        ElementTree.fromstring(content)

    def test_generate_reviews_feed_with_logs(
        self, temp_db: Path, sample_sync_logs: list
    ):
        """Test generating reviews feed with sync logs."""
        with patch("src.api.feeds.get_settings") as mock_settings:
            mock_settings.return_value.audio_public_url = "https://example.com"

            content = generate_reviews_feed()

        assert "Semaine du" in content
        assert "10 articles" in content or "11 articles" in content

        # Validate XML
        root = ElementTree.fromstring(content)
        items = root.findall(".//item")
        assert len(items) == 3

    def test_generate_reviews_feed_excludes_incomplete(self, temp_db: Path):
        """Test that incomplete sync logs are excluded."""
        # Create a completed log
        log1 = create_sync_log(notebook_id="notebook:1", bookmarks_count=5)
        update_sync_log(log1.id, status="completed")

        # Create a failed log
        log2 = create_sync_log(notebook_id="notebook:2", bookmarks_count=3)
        update_sync_log(log2.id, status="failed", error="Test error")

        # Create a running log
        create_sync_log(notebook_id="notebook:3", bookmarks_count=2)

        with patch("src.api.feeds.get_settings") as mock_settings:
            mock_settings.return_value.audio_public_url = "https://example.com"

            content = generate_reviews_feed()

        # Only the completed log should be in the feed
        root = ElementTree.fromstring(content)
        items = root.findall(".//item")
        assert len(items) == 1


class TestFeedEndpoints:
    """Tests for feed API endpoints."""

    def test_get_podcast_feed(self, temp_db: Path, sample_episodes: list):
        """Test GET /feeds/podcast.rss endpoint."""
        with patch("src.api.feeds.get_settings") as mock_settings:
            mock_settings.return_value.audio_public_url = "https://example.com/audio"

            response = client.get("/feeds/podcast.rss")

        assert response.status_code == 200
        assert "application/rss+xml" in response.headers["content-type"]
        assert "<?xml" in response.text

    def test_get_reviews_feed(self, temp_db: Path, sample_sync_logs: list):
        """Test GET /feeds/reviews.rss endpoint."""
        with patch("src.api.feeds.get_settings") as mock_settings:
            mock_settings.return_value.audio_public_url = "https://example.com"

            response = client.get("/feeds/reviews.rss")

        assert response.status_code == 200
        assert "application/rss+xml" in response.headers["content-type"]
        assert "<?xml" in response.text

    def test_regenerate_feeds(self, temp_db: Path):
        """Test POST /feeds/regenerate endpoint."""
        with patch("src.api.feeds.get_settings") as mock_settings:
            mock_settings.return_value.audio_public_url = "https://example.com"

            response = client.post("/feeds/regenerate")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "regenerated" in data["message"].lower()


class TestFeedValidation:
    """Tests for feed XML validation."""

    def test_podcast_feed_is_valid_xml(self, temp_db: Path, sample_episodes: list):
        """Test that podcast feed is valid XML."""
        with patch("src.api.feeds.get_settings") as mock_settings:
            mock_settings.return_value.audio_public_url = "https://example.com/audio"

            content = generate_podcast_feed()

        # Should not raise
        root = ElementTree.fromstring(content)
        assert root.tag == "rss"
        assert root.get("version") == "2.0"

    def test_reviews_feed_is_valid_xml(self, temp_db: Path, sample_sync_logs: list):
        """Test that reviews feed is valid XML."""
        with patch("src.api.feeds.get_settings") as mock_settings:
            mock_settings.return_value.audio_public_url = "https://example.com"

            content = generate_reviews_feed()

        # Should not raise
        root = ElementTree.fromstring(content)
        assert root.tag == "rss"
        assert root.get("version") == "2.0"

    def test_podcast_feed_has_enclosure(self, temp_db: Path, sample_episodes: list):
        """Test that podcast feed items have enclosure for audio."""
        with patch("src.api.feeds.get_settings") as mock_settings:
            mock_settings.return_value.audio_public_url = "https://example.com/audio"

            content = generate_podcast_feed()

        root = ElementTree.fromstring(content)
        items = root.findall(".//item")

        for item in items:
            enclosure = item.find("enclosure")
            assert enclosure is not None
            assert enclosure.get("url") is not None
            assert enclosure.get("type") == "audio/mpeg"
