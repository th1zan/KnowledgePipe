"""Tests for the RSS fetcher job."""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import feedparser
import pytest
from sqlalchemy import create_engine

from src.database import Base, reset_engine, set_engine
from src.jobs.rss_fetcher import (
    FeedEntry,
    ProcessingResult,
    fetch_feed,
    parse_feed_entry,
    process_all_feeds,
    process_entry,
    run_rss_job,
)


# Sample RSS feed XML for testing
SAMPLE_RSS_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <link>https://example.com</link>
    <description>A test RSS feed</description>
    <item>
      <title>Article One</title>
      <link>https://example.com/article-1</link>
      <guid>guid-1</guid>
      <description>First article description</description>
    </item>
    <item>
      <title>Article Two</title>
      <link>https://example.com/article-2</link>
      <guid>guid-2</guid>
      <description>Second article description</description>
    </item>
  </channel>
</rss>
"""

EMPTY_RSS_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Empty Feed</title>
    <link>https://example.com</link>
    <description>An empty RSS feed</description>
  </channel>
</rss>
"""

MALFORMED_RSS_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Malformed Feed</title>
    <item>
      <title>No Link Article</title>
      <!-- Missing link and guid -->
    </item>
    <item>
      <title>Valid Article</title>
      <link>https://example.com/valid</link>
      <guid>valid-guid</guid>
    </item>
  </channel>
</rss>
"""


def make_parsed_feed(xml_string: str):
    """Parse an XML string into a feedparser result."""
    return feedparser.parse(xml_string)


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
    client.add_bookmark.return_value = "bookmark-123"
    return client


class TestParseFeedEntry:
    """Tests for parse_feed_entry function."""

    def test_parse_entry_with_all_fields(self):
        """Test parsing an entry with all fields present."""
        entry = {
            "id": "unique-id",
            "link": "https://example.com/article",
            "title": "Article Title",
        }

        result = parse_feed_entry(entry, "https://feed.example.com", "Test Feed")

        assert result.guid == "unique-id"
        assert result.url == "https://example.com/article"
        assert result.title == "Article Title"
        assert result.feed_url == "https://feed.example.com"
        assert result.feed_title == "Test Feed"

    def test_parse_entry_uses_link_as_guid_fallback(self):
        """Test that link is used as guid when id is missing."""
        entry = {
            "link": "https://example.com/article",
            "title": "Article Title",
        }

        result = parse_feed_entry(entry, "https://feed.example.com", "Test Feed")

        assert result.guid == "https://example.com/article"
        assert result.url == "https://example.com/article"

    def test_parse_entry_with_missing_title(self):
        """Test parsing an entry without a title."""
        entry = {
            "id": "guid-123",
            "link": "https://example.com/article",
        }

        result = parse_feed_entry(entry, "https://feed.example.com", None)

        assert result.title is None
        assert result.feed_title is None


class TestFetchFeed:
    """Tests for fetch_feed function."""

    def test_fetch_feed_success(self):
        """Test successfully fetching a feed."""
        parsed = make_parsed_feed(SAMPLE_RSS_FEED)

        with patch("src.jobs.rss_fetcher.feedparser.parse", return_value=parsed):
            entries = fetch_feed("https://example.com/feed.xml")

        assert len(entries) == 2
        assert entries[0].guid == "guid-1"
        assert entries[0].title == "Article One"
        assert entries[0].url == "https://example.com/article-1"
        assert entries[0].feed_title == "Test Feed"
        assert entries[1].guid == "guid-2"

    def test_fetch_feed_empty(self):
        """Test fetching an empty feed."""
        parsed = make_parsed_feed(EMPTY_RSS_FEED)

        with patch("src.jobs.rss_fetcher.feedparser.parse", return_value=parsed):
            entries = fetch_feed("https://example.com/empty.xml")

        assert len(entries) == 0

    def test_fetch_feed_invalid_url(self):
        """Test fetching with an invalid URL."""
        with pytest.raises(ValueError, match="Invalid feed URL"):
            fetch_feed("not-a-valid-url")

    def test_fetch_feed_empty_url(self):
        """Test fetching with an empty URL."""
        with pytest.raises(ValueError, match="Invalid feed URL"):
            fetch_feed("")

    def test_fetch_feed_skips_entries_without_required_fields(self):
        """Test that entries without guid/link are skipped."""
        parsed = make_parsed_feed(MALFORMED_RSS_FEED)

        with patch("src.jobs.rss_fetcher.feedparser.parse", return_value=parsed):
            entries = fetch_feed("https://example.com/malformed.xml")

        # Only the valid entry should be returned
        assert len(entries) == 1
        assert entries[0].guid == "valid-guid"

    def test_fetch_feed_network_error(self):
        """Test handling network errors."""
        error_feed = SimpleNamespace(
            bozo=True,
            bozo_exception=OSError("Network unreachable"),
            entries=[],
            feed={},
        )

        with patch("src.jobs.rss_fetcher.feedparser.parse", return_value=error_feed):
            with pytest.raises(ValueError, match="Failed to fetch feed"):
                fetch_feed("https://example.com/unreachable.xml")


class TestProcessEntry:
    """Tests for process_entry function."""

    def test_process_entry_new(self, temp_db: Path, mock_readeck_client: MagicMock):
        """Test processing a new entry."""
        entry = FeedEntry(
            guid="new-guid",
            url="https://example.com/new-article",
            title="New Article",
            feed_url="https://feed.example.com",
            feed_title="Test Feed",
        )

        result = process_entry(entry, mock_readeck_client)

        assert result is True
        mock_readeck_client.add_bookmark.assert_called_once_with(
            url="https://example.com/new-article",
            title="New Article",
            labels=["rss", "Test Feed"],
        )

    def test_process_entry_duplicate(
        self, temp_db: Path, mock_readeck_client: MagicMock
    ):
        """Test that duplicate entries are skipped."""
        entry = FeedEntry(
            guid="duplicate-guid",
            url="https://example.com/article",
            title="Article",
            feed_url="https://feed.example.com",
            feed_title="Test Feed",
        )

        # First call should succeed
        result1 = process_entry(entry, mock_readeck_client)
        assert result1 is True

        # Reset the mock to track second call
        mock_readeck_client.reset_mock()

        # Second call should be skipped (already processed)
        result2 = process_entry(entry, mock_readeck_client)
        assert result2 is False
        mock_readeck_client.add_bookmark.assert_not_called()

    def test_process_entry_readeck_error(
        self, temp_db: Path, mock_readeck_client: MagicMock
    ):
        """Test handling Readeck API errors."""
        mock_readeck_client.add_bookmark.side_effect = Exception("API Error")

        entry = FeedEntry(
            guid="error-guid",
            url="https://example.com/error",
            title="Error Article",
            feed_url="https://feed.example.com",
            feed_title="Test Feed",
        )

        result = process_entry(entry, mock_readeck_client)

        assert result is False

    def test_process_entry_readeck_returns_none(
        self, temp_db: Path, mock_readeck_client: MagicMock
    ):
        """Test handling when Readeck returns None (failure)."""
        mock_readeck_client.add_bookmark.return_value = None

        entry = FeedEntry(
            guid="none-guid",
            url="https://example.com/none",
            title="None Article",
            feed_url="https://feed.example.com",
            feed_title="Test Feed",
        )

        result = process_entry(entry, mock_readeck_client)

        assert result is False

    def test_process_entry_with_custom_labels(
        self, temp_db: Path, mock_readeck_client: MagicMock
    ):
        """Test processing entry with custom labels."""
        entry = FeedEntry(
            guid="labeled-guid",
            url="https://example.com/labeled",
            title="Labeled Article",
            feed_url="https://feed.example.com",
            feed_title="Feed Title",
        )

        process_entry(entry, mock_readeck_client, labels=["tech", "news"])

        mock_readeck_client.add_bookmark.assert_called_once_with(
            url="https://example.com/labeled",
            title="Labeled Article",
            labels=["tech", "news", "rss", "Feed Title"],
        )


class TestProcessAllFeeds:
    """Tests for process_all_feeds function."""

    def test_process_all_feeds_success(
        self, temp_db: Path, mock_readeck_client: MagicMock
    ):
        """Test processing multiple feeds successfully."""
        parsed_feed1 = make_parsed_feed(SAMPLE_RSS_FEED)
        parsed_feed2 = make_parsed_feed(EMPTY_RSS_FEED)

        def mock_parse(url, **kwargs):
            if "feed1" in url:
                return parsed_feed1
            return parsed_feed2

        with patch("src.jobs.rss_fetcher.feedparser.parse", side_effect=mock_parse):
            result = process_all_feeds(
                feed_urls=[
                    "https://feed1.example.com/rss",
                    "https://feed2.example.com/rss",
                ],
                readeck_client=mock_readeck_client,
            )

        assert result.total_entries == 2
        assert result.new_entries == 2
        assert result.added_count == 2
        assert result.failed_count == 0
        assert len(result.errors) == 0

    def test_process_all_feeds_with_fetch_error(
        self, temp_db: Path, mock_readeck_client: MagicMock
    ):
        """Test processing feeds when one fails to fetch."""
        parsed_feed = make_parsed_feed(SAMPLE_RSS_FEED)
        error_feed = SimpleNamespace(
            bozo=True,
            bozo_exception=OSError("Connection refused"),
            entries=[],
            feed={},
        )

        def mock_parse(url, **kwargs):
            if "bad-feed" in url:
                return error_feed
            return parsed_feed

        with patch("src.jobs.rss_fetcher.feedparser.parse", side_effect=mock_parse):
            result = process_all_feeds(
                feed_urls=[
                    "https://feed1.example.com/rss",
                    "https://bad-feed.example.com/rss",
                ],
                readeck_client=mock_readeck_client,
            )

        # First feed should succeed
        assert result.total_entries == 2
        assert result.added_count == 2
        # Error from second feed
        assert len(result.errors) == 1
        assert "bad-feed" in result.errors[0]

    def test_process_all_feeds_no_feeds_configured(self, temp_db: Path):
        """Test processing when no feeds are configured."""
        with patch("src.jobs.rss_fetcher.get_settings") as mock_settings:
            mock_settings.return_value.rss_feed_list = []

            result = process_all_feeds()

            assert result.total_entries == 0
            assert result.added_count == 0
            assert "No feeds configured" in result.errors

    def test_process_all_feeds_mixed_results(
        self, temp_db: Path, mock_readeck_client: MagicMock
    ):
        """Test processing with mixed success/failure entries."""
        parsed_feed = make_parsed_feed(SAMPLE_RSS_FEED)

        # First entry succeeds, second fails
        mock_readeck_client.add_bookmark.side_effect = [
            "bookmark-1",
            None,  # Second entry fails
        ]

        with patch("src.jobs.rss_fetcher.feedparser.parse", return_value=parsed_feed):
            result = process_all_feeds(
                feed_urls=["https://feed.example.com/rss"],
                readeck_client=mock_readeck_client,
            )

        assert result.total_entries == 2
        assert result.new_entries == 2
        assert result.added_count == 1
        assert result.failed_count == 1


class TestRunRssJob:
    """Tests for run_rss_job function."""

    def test_run_rss_job_success(self, temp_db: Path, mock_readeck_client: MagicMock):
        """Test running the full RSS job."""
        parsed_feed = make_parsed_feed(SAMPLE_RSS_FEED)

        with patch("src.jobs.rss_fetcher.get_settings") as mock_settings:
            mock_settings.return_value.rss_feed_list = ["https://feed.example.com/rss"]
            mock_settings.return_value.readeck_url = "http://readeck:8000"
            mock_settings.return_value.readeck_token = "test-token"

            with patch(
                "src.jobs.rss_fetcher.feedparser.parse", return_value=parsed_feed
            ):
                with patch(
                    "src.jobs.rss_fetcher.ReadeckClient",
                    return_value=mock_readeck_client,
                ):
                    result = run_rss_job()

        assert isinstance(result, ProcessingResult)
        assert result.total_entries == 2

    def test_run_rss_job_handles_exception(self, temp_db: Path):
        """Test that run_rss_job handles exceptions gracefully."""
        with patch(
            "src.jobs.rss_fetcher.process_all_feeds",
            side_effect=Exception("Unexpected error"),
        ):
            result = run_rss_job()

        assert result.added_count == 0
        assert "Job failed" in result.errors[0]
