"""Tests for the database module."""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine

from src.database import (
    Base,
    Episode,
    RssItem,
    SyncLog,
    add_episode,
    add_rss_item,
    create_sync_log,
    get_episode_by_id,
    get_latest_episodes,
    get_latest_sync_logs,
    get_rss_item_by_guid,
    get_session,
    get_uploaded_episodes,
    init_db,
    is_rss_item_processed,
    mark_episode_uploaded,
    reset_engine,
    set_engine,
    update_sync_log,
)


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
        # Set the test engine
        set_engine(engine)
        # Create tables
        Base.metadata.create_all(engine)
        yield db_path
        # Cleanup
        reset_engine()


class TestInitDb:
    """Tests for database initialization."""

    def test_init_db_creates_tables(self, temp_db: Path):
        """Test that init_db creates all expected tables."""
        # Tables are already created by fixture, but we can verify they exist
        with get_session() as session:
            # Try to query each table - should not raise
            session.query(RssItem).first()
            session.query(SyncLog).first()
            session.query(Episode).first()

    def test_init_db_is_idempotent(self, temp_db: Path):
        """Test that init_db can be called multiple times safely."""
        # First call in fixture, second call here
        init_db()
        init_db()
        # Should not raise any errors


class TestRssItem:
    """Tests for RSS item operations."""

    def test_add_rss_item(self, temp_db: Path):
        """Test adding an RSS item."""
        item = add_rss_item(
            guid="unique-guid-123",
            url="https://example.com/article",
            title="Test Article",
            feed_url="https://example.com/feed.xml",
            bookmark_id="bm-123",
        )

        assert item.id is not None
        assert item.guid == "unique-guid-123"
        assert item.url == "https://example.com/article"
        assert item.title == "Test Article"
        assert item.feed_url == "https://example.com/feed.xml"
        assert item.bookmark_id == "bm-123"
        assert item.created_at is not None

    def test_add_rss_item_without_optional_fields(self, temp_db: Path):
        """Test adding an RSS item without optional fields."""
        item = add_rss_item(
            guid="guid-no-title",
            url="https://example.com/article2",
            title=None,
            feed_url="https://example.com/feed.xml",
        )

        assert item.id is not None
        assert item.title is None
        assert item.bookmark_id is None

    def test_is_rss_item_processed_true(self, temp_db: Path):
        """Test that is_rss_item_processed returns True for existing items."""
        add_rss_item(
            guid="existing-guid",
            url="https://example.com/article",
            title="Existing",
            feed_url="https://example.com/feed.xml",
        )

        assert is_rss_item_processed("existing-guid") is True

    def test_is_rss_item_processed_false(self, temp_db: Path):
        """Test that is_rss_item_processed returns False for non-existing items."""
        assert is_rss_item_processed("non-existing-guid") is False

    def test_get_rss_item_by_guid_found(self, temp_db: Path):
        """Test getting an RSS item by GUID when it exists."""
        add_rss_item(
            guid="findable-guid",
            url="https://example.com/article",
            title="Findable",
            feed_url="https://example.com/feed.xml",
        )

        item = get_rss_item_by_guid("findable-guid")
        assert item is not None
        assert item.guid == "findable-guid"
        assert item.title == "Findable"

    def test_get_rss_item_by_guid_not_found(self, temp_db: Path):
        """Test getting an RSS item by GUID when it doesn't exist."""
        item = get_rss_item_by_guid("unknown-guid")
        assert item is None

    def test_add_duplicate_guid_raises_error(self, temp_db: Path):
        """Test that adding a duplicate GUID raises an error."""
        add_rss_item(
            guid="duplicate-guid",
            url="https://example.com/article1",
            title="First",
            feed_url="https://example.com/feed.xml",
        )

        with pytest.raises(Exception):  # IntegrityError wrapped
            add_rss_item(
                guid="duplicate-guid",
                url="https://example.com/article2",
                title="Second",
                feed_url="https://example.com/feed.xml",
            )


class TestSyncLog:
    """Tests for sync log operations."""

    def test_create_sync_log(self, temp_db: Path):
        """Test creating a sync log."""
        log = create_sync_log(
            notebook_id="notebook:abc123",
            bookmarks_count=10,
        )

        assert log.id is not None
        assert log.status == "running"
        assert log.notebook_id == "notebook:abc123"
        assert log.bookmarks_count == 10
        assert log.started_at is not None
        assert log.completed_at is None
        assert log.error is None

    def test_create_sync_log_without_notebook(self, temp_db: Path):
        """Test creating a sync log without notebook ID."""
        log = create_sync_log(bookmarks_count=5)

        assert log.id is not None
        assert log.notebook_id is None
        assert log.bookmarks_count == 5

    def test_update_sync_log_completed(self, temp_db: Path):
        """Test updating a sync log to completed status."""
        log = create_sync_log(notebook_id="notebook:123", bookmarks_count=5)
        log_id = log.id

        updated = update_sync_log(log_id, status="completed")

        assert updated is not None
        assert updated.status == "completed"
        assert updated.completed_at is not None
        assert updated.error is None

    def test_update_sync_log_failed_with_error(self, temp_db: Path):
        """Test updating a sync log to failed status with error."""
        log = create_sync_log(notebook_id="notebook:123", bookmarks_count=5)
        log_id = log.id

        updated = update_sync_log(
            log_id,
            status="failed",
            error="Connection timeout to Open Notebook",
        )

        assert updated is not None
        assert updated.status == "failed"
        assert updated.completed_at is not None
        assert updated.error == "Connection timeout to Open Notebook"

    def test_update_sync_log_with_new_notebook_id(self, temp_db: Path):
        """Test updating a sync log with a new notebook ID."""
        log = create_sync_log(bookmarks_count=5)
        log_id = log.id

        updated = update_sync_log(
            log_id,
            status="running",
            notebook_id="notebook:new123",
            bookmarks_count=10,
        )

        assert updated is not None
        assert updated.notebook_id == "notebook:new123"
        assert updated.bookmarks_count == 10

    def test_update_sync_log_not_found(self, temp_db: Path):
        """Test updating a non-existent sync log."""
        updated = update_sync_log(99999, status="completed")
        assert updated is None

    def test_get_latest_sync_logs(self, temp_db: Path):
        """Test getting the latest sync logs."""
        # Create multiple logs
        for i in range(5):
            create_sync_log(notebook_id=f"notebook:{i}", bookmarks_count=i)

        logs = get_latest_sync_logs(limit=3)

        assert len(logs) == 3
        # Should be ordered by started_at descending (most recent first)
        assert logs[0].notebook_id == "notebook:4"
        assert logs[1].notebook_id == "notebook:3"
        assert logs[2].notebook_id == "notebook:2"

    def test_get_latest_sync_logs_empty(self, temp_db: Path):
        """Test getting sync logs when none exist."""
        logs = get_latest_sync_logs(limit=10)
        assert logs == []


class TestEpisode:
    """Tests for episode operations."""

    def test_add_episode(self, temp_db: Path):
        """Test adding an episode."""
        episode = add_episode(
            notebook_id="notebook:abc123",
            episode_id="podcast_episode:xyz789",
            episode_name="Week of January 15, 2024",
            audio_url="/api/podcasts/episodes/xyz789/audio",
        )

        assert episode.id is not None
        assert episode.notebook_id == "notebook:abc123"
        assert episode.episode_id == "podcast_episode:xyz789"
        assert episode.episode_name == "Week of January 15, 2024"
        assert episode.audio_url == "/api/podcasts/episodes/xyz789/audio"
        assert episode.uploaded is False
        assert episode.public_url is None
        assert episode.created_at is not None

    def test_add_episode_minimal(self, temp_db: Path):
        """Test adding an episode with minimal fields."""
        episode = add_episode(
            notebook_id="notebook:abc",
            episode_id="episode:123",
        )

        assert episode.id is not None
        assert episode.episode_name is None
        assert episode.audio_url is None

    def test_mark_episode_uploaded(self, temp_db: Path):
        """Test marking an episode as uploaded."""
        episode = add_episode(
            notebook_id="notebook:abc",
            episode_id="episode:upload-test",
            episode_name="Test Episode",
        )

        updated = mark_episode_uploaded(
            episode_id="episode:upload-test",
            public_url="https://cdn.example.com/episodes/upload-test.mp3",
        )

        assert updated is not None
        assert updated.uploaded is True
        assert updated.public_url == "https://cdn.example.com/episodes/upload-test.mp3"

    def test_mark_episode_uploaded_not_found(self, temp_db: Path):
        """Test marking a non-existent episode as uploaded."""
        updated = mark_episode_uploaded(
            episode_id="non-existent",
            public_url="https://example.com/audio.mp3",
        )
        assert updated is None

    def test_get_episode_by_id_found(self, temp_db: Path):
        """Test getting an episode by ID when it exists."""
        add_episode(
            notebook_id="notebook:abc",
            episode_id="episode:findable",
            episode_name="Findable Episode",
        )

        episode = get_episode_by_id("episode:findable")
        assert episode is not None
        assert episode.episode_name == "Findable Episode"

    def test_get_episode_by_id_not_found(self, temp_db: Path):
        """Test getting an episode by ID when it doesn't exist."""
        episode = get_episode_by_id("episode:unknown")
        assert episode is None

    def test_get_latest_episodes(self, temp_db: Path):
        """Test getting the latest episodes."""
        # Create multiple episodes
        for i in range(5):
            add_episode(
                notebook_id=f"notebook:{i}",
                episode_id=f"episode:{i}",
                episode_name=f"Episode {i}",
            )

        episodes = get_latest_episodes(limit=3)

        assert len(episodes) == 3
        # Should be ordered by created_at descending
        assert episodes[0].episode_name == "Episode 4"
        assert episodes[1].episode_name == "Episode 3"
        assert episodes[2].episode_name == "Episode 2"

    def test_get_latest_episodes_empty(self, temp_db: Path):
        """Test getting episodes when none exist."""
        episodes = get_latest_episodes(limit=10)
        assert episodes == []

    def test_get_uploaded_episodes(self, temp_db: Path):
        """Test getting only uploaded episodes."""
        # Create mix of uploaded and non-uploaded episodes
        for i in range(5):
            add_episode(
                notebook_id=f"notebook:{i}",
                episode_id=f"episode:{i}",
                episode_name=f"Episode {i}",
            )
            if i % 2 == 0:  # Mark even ones as uploaded
                mark_episode_uploaded(
                    episode_id=f"episode:{i}",
                    public_url=f"https://cdn.example.com/{i}.mp3",
                )

        uploaded = get_uploaded_episodes(limit=10)

        assert len(uploaded) == 3  # Episodes 0, 2, 4
        for ep in uploaded:
            assert ep.uploaded is True
            assert ep.public_url is not None

    def test_add_duplicate_episode_id_raises_error(self, temp_db: Path):
        """Test that adding a duplicate episode ID raises an error."""
        add_episode(
            notebook_id="notebook:abc",
            episode_id="episode:duplicate",
            episode_name="First",
        )

        with pytest.raises(Exception):  # IntegrityError wrapped
            add_episode(
                notebook_id="notebook:xyz",
                episode_id="episode:duplicate",
                episode_name="Second",
            )


class TestSessionManagement:
    """Tests for session management."""

    def test_session_rollback_on_error(self, temp_db: Path):
        """Test that session rolls back on error."""
        # First, add an item successfully
        add_rss_item(
            guid="rollback-test",
            url="https://example.com/article",
            title="Test",
            feed_url="https://example.com/feed.xml",
        )

        # Try to add a duplicate (should fail and rollback)
        with pytest.raises(Exception):
            add_rss_item(
                guid="rollback-test",
                url="https://example.com/article2",
                title="Test2",
                feed_url="https://example.com/feed.xml",
            )

        # Original item should still exist
        assert is_rss_item_processed("rollback-test") is True
