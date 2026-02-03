"""Tests for the weekly sync job."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine

from src.database import Base, Episode, SyncLog, get_session, reset_engine, set_engine
from src.jobs.weekly_sync import (
    Bookmark,
    GenerationResult,
    SyncResult,
    add_sources_to_notebook,
    create_weekly_notebook,
    get_week_bookmarks,
    run_weekly_sync,
    trigger_generations,
    wait_for_sources,
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
        set_engine(engine)
        Base.metadata.create_all(engine)
        yield db_path
        reset_engine()


@pytest.fixture
def mock_readeck_client():
    """Create a mock Readeck client."""
    client = MagicMock()
    client.get_week_bookmarks.return_value = [
        {
            "id": "bm-1",
            "url": "https://example.com/article-1",
            "title": "Article One",
            "type": "article",
        },
        {
            "id": "bm-2",
            "url": "https://example.com/article-2",
            "title": "Article Two",
            "type": "article",
        },
    ]
    client.get_bookmark_content.return_value = "# PDF Content"
    return client


@pytest.fixture
def mock_on_client():
    """Create a mock Open Notebook client."""
    client = MagicMock()
    client.create_notebook.return_value = {
        "id": "notebook:abc123",
        "name": "Test Notebook",
    }
    client.add_source_url.return_value = {"id": "source:url1"}
    client.add_source_text.return_value = {"id": "source:text1"}
    client.wait_for_source.return_value = True
    client.generate_podcast.return_value = {"job_id": "job:123"}
    client.wait_for_podcast.return_value = "episode:xyz"
    client.list_episodes.return_value = [
        {"id": "episode:xyz", "audio_url": "/api/podcasts/episodes/xyz/audio"}
    ]
    client.get_notebook_notes.return_value = [
        {"note_type": "ai", "title": "Summary", "content": "This is a summary."}
    ]
    return client


class TestGetWeekBookmarks:
    """Tests for get_week_bookmarks function."""

    def test_get_week_bookmarks_success(self, mock_readeck_client: MagicMock):
        """Test getting bookmarks from the past week."""
        with patch("src.jobs.weekly_sync.get_settings") as mock_settings:
            mock_settings.return_value.readeck_url = "http://readeck:8000"
            mock_settings.return_value.readeck_token = "token"

            bookmarks = get_week_bookmarks(mock_readeck_client)

        assert len(bookmarks) == 2
        assert bookmarks[0].id == "bm-1"
        assert bookmarks[0].url == "https://example.com/article-1"
        assert bookmarks[0].title == "Article One"
        assert bookmarks[0].is_pdf is False

    def test_get_week_bookmarks_with_pdf(self, mock_readeck_client: MagicMock):
        """Test getting bookmarks including PDFs."""
        mock_readeck_client.get_week_bookmarks.return_value = [
            {
                "id": "pdf-1",
                "url": "https://example.com/document.pdf",
                "title": "PDF Document",
                "type": "pdf",
            }
        ]

        with patch("src.jobs.weekly_sync.get_settings") as mock_settings:
            mock_settings.return_value.readeck_url = "http://readeck:8000"
            mock_settings.return_value.readeck_token = "token"

            bookmarks = get_week_bookmarks(mock_readeck_client)

        assert len(bookmarks) == 1
        assert bookmarks[0].is_pdf is True
        assert bookmarks[0].content == "# PDF Content"
        mock_readeck_client.get_bookmark_content.assert_called_once_with(
            "pdf-1", format="md"
        )

    def test_get_week_bookmarks_empty(self, mock_readeck_client: MagicMock):
        """Test getting bookmarks when none exist."""
        mock_readeck_client.get_week_bookmarks.return_value = []

        with patch("src.jobs.weekly_sync.get_settings") as mock_settings:
            mock_settings.return_value.readeck_url = "http://readeck:8000"
            mock_settings.return_value.readeck_token = "token"

            bookmarks = get_week_bookmarks(mock_readeck_client)

        assert len(bookmarks) == 0


class TestCreateWeeklyNotebook:
    """Tests for create_weekly_notebook function."""

    def test_create_weekly_notebook(self, mock_on_client: MagicMock):
        """Test creating a weekly notebook."""
        bookmarks = [
            Bookmark(id="1", url="https://example.com/1", title="Article 1"),
            Bookmark(id="2", url="https://example.com/2", title="Article 2"),
        ]

        with patch("src.jobs.weekly_sync.get_settings") as mock_settings:
            mock_settings.return_value.open_notebook_url = "http://on:5055"
            mock_settings.return_value.open_notebook_password = "pass"

            notebook_id = create_weekly_notebook(bookmarks, mock_on_client)

        assert notebook_id == "notebook:abc123"
        mock_on_client.create_notebook.assert_called_once()
        call_kwargs = mock_on_client.create_notebook.call_args[1]
        assert "2 articles" in call_kwargs["description"]

    def test_create_weekly_notebook_custom_name(self, mock_on_client: MagicMock):
        """Test creating a notebook with custom name."""
        bookmarks = [Bookmark(id="1", url="https://example.com/1", title="Article")]

        with patch("src.jobs.weekly_sync.get_settings") as mock_settings:
            mock_settings.return_value.open_notebook_url = "http://on:5055"
            mock_settings.return_value.open_notebook_password = "pass"

            notebook_id = create_weekly_notebook(
                bookmarks, mock_on_client, notebook_name="Custom Name"
            )

        assert notebook_id == "notebook:abc123"
        mock_on_client.create_notebook.assert_called_once_with(
            name="Custom Name", description="1 articles"
        )


class TestAddSourcesToNotebook:
    """Tests for add_sources_to_notebook function."""

    def test_add_sources_url(self, mock_on_client: MagicMock):
        """Test adding URL sources to notebook."""
        bookmarks = [
            Bookmark(id="1", url="https://example.com/1", title="Article 1"),
            Bookmark(id="2", url="https://example.com/2", title="Article 2"),
        ]

        with patch("src.jobs.weekly_sync.get_settings") as mock_settings:
            mock_settings.return_value.open_notebook_url = "http://on:5055"
            mock_settings.return_value.open_notebook_password = "pass"

            source_ids, failures = add_sources_to_notebook(
                "notebook:123", bookmarks, mock_on_client
            )

        assert len(source_ids) == 2
        assert failures == 0
        assert mock_on_client.add_source_url.call_count == 2

    def test_add_sources_pdf_as_text(self, mock_on_client: MagicMock):
        """Test adding PDF content as text source."""
        bookmarks = [
            Bookmark(
                id="pdf-1",
                url="https://example.com/doc.pdf",
                title="PDF Doc",
                is_pdf=True,
                content="# PDF Content Here",
            ),
        ]

        with patch("src.jobs.weekly_sync.get_settings") as mock_settings:
            mock_settings.return_value.open_notebook_url = "http://on:5055"
            mock_settings.return_value.open_notebook_password = "pass"

            source_ids, failures = add_sources_to_notebook(
                "notebook:123", bookmarks, mock_on_client
            )

        assert len(source_ids) == 1
        assert failures == 0
        mock_on_client.add_source_text.assert_called_once_with(
            notebook_id="notebook:123",
            content="# PDF Content Here",
            title="PDF Doc",
            embed=True,
        )

    def test_add_sources_pdf_without_content_uses_url(self, mock_on_client: MagicMock):
        """Test that PDFs without extracted content are added as URL."""
        bookmarks = [
            Bookmark(
                id="pdf-1",
                url="https://example.com/doc.pdf",
                title="PDF Doc",
                is_pdf=True,
                content=None,  # No extracted content
            ),
        ]

        with patch("src.jobs.weekly_sync.get_settings") as mock_settings:
            mock_settings.return_value.open_notebook_url = "http://on:5055"
            mock_settings.return_value.open_notebook_password = "pass"

            source_ids, failures = add_sources_to_notebook(
                "notebook:123", bookmarks, mock_on_client
            )

        assert len(source_ids) == 1
        mock_on_client.add_source_url.assert_called_once()

    def test_add_sources_partial_failure(self, mock_on_client: MagicMock):
        """Test handling when some sources fail to add."""
        bookmarks = [
            Bookmark(id="1", url="https://example.com/1", title="Article 1"),
            Bookmark(id="2", url="https://example.com/2", title="Article 2"),
        ]

        # First succeeds, second fails
        mock_on_client.add_source_url.side_effect = [
            {"id": "source:1"},
            Exception("API Error"),
        ]

        with patch("src.jobs.weekly_sync.get_settings") as mock_settings:
            mock_settings.return_value.open_notebook_url = "http://on:5055"
            mock_settings.return_value.open_notebook_password = "pass"

            source_ids, failures = add_sources_to_notebook(
                "notebook:123", bookmarks, mock_on_client
            )

        assert len(source_ids) == 1
        assert failures == 1


class TestWaitForSources:
    """Tests for wait_for_sources function."""

    def test_wait_for_sources_all_success(self, mock_on_client: MagicMock):
        """Test waiting for sources when all succeed."""
        source_ids = ["source:1", "source:2", "source:3"]

        with patch("src.jobs.weekly_sync.get_settings") as mock_settings:
            mock_settings.return_value.open_notebook_url = "http://on:5055"
            mock_settings.return_value.open_notebook_password = "pass"
            mock_settings.return_value.source_processing_timeout = 300

            success, failed = wait_for_sources(source_ids, mock_on_client)

        assert success == 3
        assert failed == 0

    def test_wait_for_sources_partial_failure(self, mock_on_client: MagicMock):
        """Test waiting for sources with some failures."""
        source_ids = ["source:1", "source:2", "source:3"]
        mock_on_client.wait_for_source.side_effect = [True, False, True]

        with patch("src.jobs.weekly_sync.get_settings") as mock_settings:
            mock_settings.return_value.open_notebook_url = "http://on:5055"
            mock_settings.return_value.open_notebook_password = "pass"
            mock_settings.return_value.source_processing_timeout = 300

            success, failed = wait_for_sources(source_ids, mock_on_client)

        assert success == 2
        assert failed == 1

    def test_wait_for_sources_with_exception(self, mock_on_client: MagicMock):
        """Test handling exceptions during wait."""
        source_ids = ["source:1", "source:2"]
        mock_on_client.wait_for_source.side_effect = [True, Exception("Timeout")]

        with patch("src.jobs.weekly_sync.get_settings") as mock_settings:
            mock_settings.return_value.open_notebook_url = "http://on:5055"
            mock_settings.return_value.open_notebook_password = "pass"
            mock_settings.return_value.source_processing_timeout = 300

            success, failed = wait_for_sources(source_ids, mock_on_client)

        assert success == 1
        assert failed == 1


class TestTriggerGenerations:
    """Tests for trigger_generations function."""

    def test_trigger_generations_success(self, mock_on_client: MagicMock):
        """Test successful generation trigger."""
        with patch("src.jobs.weekly_sync.get_settings") as mock_settings:
            mock_settings.return_value.open_notebook_url = "http://on:5055"
            mock_settings.return_value.open_notebook_password = "pass"
            mock_settings.return_value.podcast_episode_profile = "default"
            mock_settings.return_value.podcast_speaker_profile = "default"
            mock_settings.return_value.podcast_generation_timeout = 600

            result = trigger_generations("notebook:123", on_client=mock_on_client)

        assert result.notebook_id == "notebook:123"
        assert result.episode_id == "episode:xyz"
        assert result.audio_url == "/api/podcasts/episodes/xyz/audio"
        assert result.summary == "This is a summary."
        assert result.success is True

    def test_trigger_generations_podcast_timeout(self, mock_on_client: MagicMock):
        """Test handling podcast generation timeout."""
        mock_on_client.wait_for_podcast.return_value = None

        with patch("src.jobs.weekly_sync.get_settings") as mock_settings:
            mock_settings.return_value.open_notebook_url = "http://on:5055"
            mock_settings.return_value.open_notebook_password = "pass"
            mock_settings.return_value.podcast_episode_profile = "default"
            mock_settings.return_value.podcast_speaker_profile = "default"
            mock_settings.return_value.podcast_generation_timeout = 600

            result = trigger_generations("notebook:123", on_client=mock_on_client)

        assert result.episode_id is None
        assert result.success is True  # Timeout is not a fatal error

    def test_trigger_generations_podcast_error(self, mock_on_client: MagicMock):
        """Test handling podcast generation error."""
        mock_on_client.generate_podcast.side_effect = Exception("API Error")

        with patch("src.jobs.weekly_sync.get_settings") as mock_settings:
            mock_settings.return_value.open_notebook_url = "http://on:5055"
            mock_settings.return_value.open_notebook_password = "pass"
            mock_settings.return_value.podcast_episode_profile = "default"
            mock_settings.return_value.podcast_speaker_profile = "default"
            mock_settings.return_value.podcast_generation_timeout = 600

            result = trigger_generations("notebook:123", on_client=mock_on_client)

        assert result.success is False
        assert "API Error" in result.error


class TestRunWeeklySync:
    """Tests for run_weekly_sync function."""

    def test_run_weekly_sync_full_success(
        self, temp_db: Path, mock_readeck_client: MagicMock, mock_on_client: MagicMock
    ):
        """Test running a full weekly sync successfully."""
        with patch("src.jobs.weekly_sync.get_settings") as mock_settings:
            mock_settings.return_value.readeck_url = "http://readeck:8000"
            mock_settings.return_value.readeck_token = "token"
            mock_settings.return_value.open_notebook_url = "http://on:5055"
            mock_settings.return_value.open_notebook_password = "pass"
            mock_settings.return_value.source_processing_timeout = 300
            mock_settings.return_value.podcast_episode_profile = "default"
            mock_settings.return_value.podcast_speaker_profile = "default"
            mock_settings.return_value.podcast_generation_timeout = 600

            with patch(
                "src.jobs.weekly_sync.ReadeckClient", return_value=mock_readeck_client
            ):
                with patch(
                    "src.jobs.weekly_sync.OpenNotebookClient",
                    return_value=mock_on_client,
                ):
                    result = run_weekly_sync()

        assert result.success is True
        assert result.notebook_id == "notebook:abc123"
        assert result.bookmarks_count == 2
        assert result.sources_added == 2
        assert result.episode_id == "episode:xyz"

        # Check sync log was created
        with get_session() as session:
            logs = session.query(SyncLog).all()
            assert len(logs) == 1
            assert logs[0].status == "completed"

        # Check episode was saved
        with get_session() as session:
            episodes = session.query(Episode).all()
            assert len(episodes) == 1
            assert episodes[0].episode_id == "episode:xyz"

    def test_run_weekly_sync_no_bookmarks(
        self, temp_db: Path, mock_readeck_client: MagicMock
    ):
        """Test running sync when there are no bookmarks."""
        mock_readeck_client.get_week_bookmarks.return_value = []

        with patch("src.jobs.weekly_sync.get_settings") as mock_settings:
            mock_settings.return_value.readeck_url = "http://readeck:8000"
            mock_settings.return_value.readeck_token = "token"
            mock_settings.return_value.open_notebook_url = "http://on:5055"
            mock_settings.return_value.open_notebook_password = "pass"

            with patch(
                "src.jobs.weekly_sync.ReadeckClient", return_value=mock_readeck_client
            ):
                result = run_weekly_sync()

        assert result.success is True
        assert result.notebook_id is None
        assert result.bookmarks_count == 0

    def test_run_weekly_sync_error(self, temp_db: Path, mock_readeck_client: MagicMock):
        """Test handling errors during sync."""
        mock_readeck_client.get_week_bookmarks.side_effect = Exception(
            "Connection failed"
        )

        with patch("src.jobs.weekly_sync.get_settings") as mock_settings:
            mock_settings.return_value.readeck_url = "http://readeck:8000"
            mock_settings.return_value.readeck_token = "token"
            mock_settings.return_value.open_notebook_url = "http://on:5055"
            mock_settings.return_value.open_notebook_password = "pass"

            with patch(
                "src.jobs.weekly_sync.ReadeckClient", return_value=mock_readeck_client
            ):
                result = run_weekly_sync()

        assert result.success is False
        assert "Connection failed" in result.error

        # Check sync log was marked as failed
        with get_session() as session:
            logs = session.query(SyncLog).all()
            assert len(logs) == 1
            assert logs[0].status == "failed"
