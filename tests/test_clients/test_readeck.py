"""Tests for Readeck client."""

from __future__ import annotations

import pytest
import responses
from requests.exceptions import ConnectionError as RequestsConnectionError
from responses import matchers

from src.clients.readeck import ReadeckClient, ReadeckError


class TestReadeckHealthCheck:
    """Tests for health_check method."""

    @responses.activate
    def test_health_check_success(self, readeck_base_url: str, readeck_token: str):
        """Test successful health check."""
        responses.add(
            responses.GET,
            f"{readeck_base_url}/api/profile",
            json={"username": "testuser"},
            status=200,
        )

        client = ReadeckClient(readeck_base_url, readeck_token)
        assert client.health_check() is True

    @responses.activate
    def test_health_check_unauthorized(self, readeck_base_url: str, readeck_token: str):
        """Test health check with invalid token."""
        responses.add(
            responses.GET,
            f"{readeck_base_url}/api/profile",
            json={"error": "Unauthorized"},
            status=401,
        )

        client = ReadeckClient(readeck_base_url, readeck_token)
        assert client.health_check() is False

    @responses.activate
    def test_health_check_connection_error(
        self, readeck_base_url: str, readeck_token: str
    ):
        """Test health check when server is unreachable."""
        responses.add(
            responses.GET,
            f"{readeck_base_url}/api/profile",
            body=RequestsConnectionError("Connection refused"),
        )

        client = ReadeckClient(readeck_base_url, readeck_token)
        assert client.health_check() is False


class TestReadeckAddBookmark:
    """Tests for add_bookmark method."""

    @responses.activate
    def test_add_bookmark_success(self, readeck_base_url: str, readeck_token: str):
        """Test successful bookmark creation."""
        responses.add(
            responses.POST,
            f"{readeck_base_url}/api/bookmarks",
            status=202,
            headers={"Bookmark-Id": "bm_new123"},
        )

        client = ReadeckClient(readeck_base_url, readeck_token)
        result = client.add_bookmark("https://example.com/article", title="Test")

        assert result == "bm_new123"

    @responses.activate
    def test_add_bookmark_with_labels(self, readeck_base_url: str, readeck_token: str):
        """Test bookmark creation with labels."""
        responses.add(
            responses.POST,
            f"{readeck_base_url}/api/bookmarks",
            match=[
                matchers.json_params_matcher(
                    {
                        "url": "https://example.com/article",
                        "title": "Test",
                        "labels": ["tech", "rss"],
                    }
                )
            ],
            status=202,
            headers={"Bookmark-Id": "bm_labeled"},
        )

        client = ReadeckClient(readeck_base_url, readeck_token)
        result = client.add_bookmark(
            "https://example.com/article",
            title="Test",
            labels=["tech", "rss"],
        )

        assert result == "bm_labeled"

    @responses.activate
    def test_add_bookmark_duplicate(self, readeck_base_url: str, readeck_token: str):
        """Test adding duplicate bookmark (already exists)."""
        responses.add(
            responses.POST,
            f"{readeck_base_url}/api/bookmarks",
            json={"error": "Bookmark already exists"},
            status=409,
        )

        client = ReadeckClient(readeck_base_url, readeck_token)
        result = client.add_bookmark("https://example.com/existing")

        assert result is None

    @responses.activate
    def test_add_bookmark_retry_on_500(self, readeck_base_url: str, readeck_token: str):
        """Test retry behavior on server error."""
        # First two calls fail, third succeeds
        responses.add(
            responses.POST,
            f"{readeck_base_url}/api/bookmarks",
            status=500,
        )
        responses.add(
            responses.POST,
            f"{readeck_base_url}/api/bookmarks",
            status=500,
        )
        responses.add(
            responses.POST,
            f"{readeck_base_url}/api/bookmarks",
            status=202,
            headers={"Bookmark-Id": "bm_retry"},
        )

        client = ReadeckClient(readeck_base_url, readeck_token)
        result = client.add_bookmark("https://example.com/article")

        assert result == "bm_retry"
        assert len(responses.calls) == 3


class TestReadeckGetBookmarks:
    """Tests for get_bookmarks method."""

    @responses.activate
    def test_get_bookmarks_empty(self, readeck_base_url: str, readeck_token: str):
        """Test getting bookmarks when none exist."""
        responses.add(
            responses.GET,
            f"{readeck_base_url}/api/bookmarks",
            json=[],
            status=200,
        )

        client = ReadeckClient(readeck_base_url, readeck_token)
        result = client.get_bookmarks()

        assert result == []

    @responses.activate
    def test_get_bookmarks_with_results(
        self,
        readeck_base_url: str,
        readeck_token: str,
        sample_bookmark: dict,
    ):
        """Test getting bookmarks with results."""
        responses.add(
            responses.GET,
            f"{readeck_base_url}/api/bookmarks",
            json=[sample_bookmark],
            status=200,
        )

        client = ReadeckClient(readeck_base_url, readeck_token)
        result = client.get_bookmarks()

        assert len(result) == 1
        assert result[0]["id"] == "bm_abc123"

    @responses.activate
    def test_get_bookmarks_with_date_filter(
        self,
        readeck_base_url: str,
        readeck_token: str,
        sample_bookmark: dict,
    ):
        """Test getting bookmarks with date range filter."""
        responses.add(
            responses.GET,
            f"{readeck_base_url}/api/bookmarks",
            json=[sample_bookmark],
            status=200,
        )

        client = ReadeckClient(readeck_base_url, readeck_token)
        result = client.get_bookmarks(range_start="2024-01-01", range_end="2024-01-31")

        assert len(result) == 1
        # Verify the request had correct params
        assert "range_start=2024-01-01" in responses.calls[0].request.url
        assert "range_end=2024-01-31" in responses.calls[0].request.url

    @responses.activate
    def test_get_week_bookmarks(
        self,
        readeck_base_url: str,
        readeck_token: str,
        sample_bookmark: dict,
    ):
        """Test getting bookmarks from last 7 days."""
        responses.add(
            responses.GET,
            f"{readeck_base_url}/api/bookmarks",
            json=[sample_bookmark],
            status=200,
        )

        client = ReadeckClient(readeck_base_url, readeck_token)
        result = client.get_week_bookmarks()

        assert len(result) == 1
        # Verify range_start is in the request
        assert "range_start=" in responses.calls[0].request.url


class TestReadeckGetBookmarkContent:
    """Tests for get_bookmark_content method."""

    @responses.activate
    def test_get_bookmark_content_md(self, readeck_base_url: str, readeck_token: str):
        """Test getting bookmark content as markdown."""
        markdown_content = "# Test Article\n\nThis is the content."
        responses.add(
            responses.GET,
            f"{readeck_base_url}/api/bookmarks/bm_abc123/article.md",
            body=markdown_content,
            status=200,
            content_type="text/markdown",
        )

        client = ReadeckClient(readeck_base_url, readeck_token)
        result = client.get_bookmark_content("bm_abc123", format="md")

        assert result == markdown_content

    @responses.activate
    def test_get_bookmark_content_html(self, readeck_base_url: str, readeck_token: str):
        """Test getting bookmark content as HTML."""
        html_content = "<h1>Test Article</h1><p>This is the content.</p>"
        responses.add(
            responses.GET,
            f"{readeck_base_url}/api/bookmarks/bm_abc123/article",
            body=html_content,
            status=200,
            content_type="text/html",
        )

        client = ReadeckClient(readeck_base_url, readeck_token)
        result = client.get_bookmark_content("bm_abc123", format="html")

        assert result == html_content

    @responses.activate
    def test_get_bookmark_content_not_found(
        self,
        readeck_base_url: str,
        readeck_token: str,
    ):
        """Test getting content for non-existent bookmark."""
        responses.add(
            responses.GET,
            f"{readeck_base_url}/api/bookmarks/bm_notfound/article.md",
            json={"error": "Not found"},
            status=404,
        )

        client = ReadeckClient(readeck_base_url, readeck_token)
        result = client.get_bookmark_content("bm_notfound")

        assert result is None


class TestReadeckUpdateBookmark:
    """Tests for update_bookmark method."""

    @responses.activate
    def test_update_bookmark_mark(self, readeck_base_url: str, readeck_token: str):
        """Test marking a bookmark as favorite."""
        responses.add(
            responses.PATCH,
            f"{readeck_base_url}/api/bookmarks/bm_abc123",
            status=200,
        )

        client = ReadeckClient(readeck_base_url, readeck_token)
        result = client.update_bookmark("bm_abc123", is_marked=True)

        assert result is True

    @responses.activate
    def test_update_bookmark_add_labels(
        self, readeck_base_url: str, readeck_token: str
    ):
        """Test adding labels to a bookmark."""
        responses.add(
            responses.PATCH,
            f"{readeck_base_url}/api/bookmarks/bm_abc123",
            match=[
                matchers.json_params_matcher(
                    {
                        "add_labels": ["new-label"],
                    }
                )
            ],
            status=200,
        )

        client = ReadeckClient(readeck_base_url, readeck_token)
        result = client.update_bookmark("bm_abc123", add_labels=["new-label"])

        assert result is True

    @responses.activate
    def test_update_bookmark_not_found(self, readeck_base_url: str, readeck_token: str):
        """Test updating non-existent bookmark."""
        responses.add(
            responses.PATCH,
            f"{readeck_base_url}/api/bookmarks/bm_notfound",
            status=404,
        )

        client = ReadeckClient(readeck_base_url, readeck_token)
        result = client.update_bookmark("bm_notfound", is_marked=True)

        assert result is False


class TestReadeckDeleteBookmark:
    """Tests for delete_bookmark method."""

    @responses.activate
    def test_delete_bookmark_success(self, readeck_base_url: str, readeck_token: str):
        """Test successful bookmark deletion."""
        responses.add(
            responses.DELETE,
            f"{readeck_base_url}/api/bookmarks/bm_abc123",
            status=204,
        )

        client = ReadeckClient(readeck_base_url, readeck_token)
        result = client.delete_bookmark("bm_abc123")

        assert result is True

    @responses.activate
    def test_delete_bookmark_not_found(self, readeck_base_url: str, readeck_token: str):
        """Test deleting non-existent bookmark (still succeeds)."""
        responses.add(
            responses.DELETE,
            f"{readeck_base_url}/api/bookmarks/bm_notfound",
            status=404,
        )

        client = ReadeckClient(readeck_base_url, readeck_token)
        result = client.delete_bookmark("bm_notfound")

        # 404 is considered success for delete (idempotent)
        assert result is True


class TestReadeckGetLabels:
    """Tests for get_labels method."""

    @responses.activate
    def test_get_labels_success(self, readeck_base_url: str, readeck_token: str):
        """Test getting labels."""
        labels = [
            {"name": "tech", "count": 15},
            {"name": "lecture", "count": 8},
        ]
        responses.add(
            responses.GET,
            f"{readeck_base_url}/api/bookmarks/labels",
            json=labels,
            status=200,
        )

        client = ReadeckClient(readeck_base_url, readeck_token)
        result = client.get_labels()

        assert len(result) == 2
        assert result[0]["name"] == "tech"

    @responses.activate
    def test_get_labels_empty(self, readeck_base_url: str, readeck_token: str):
        """Test getting labels when none exist."""
        responses.add(
            responses.GET,
            f"{readeck_base_url}/api/bookmarks/labels",
            json=[],
            status=200,
        )

        client = ReadeckClient(readeck_base_url, readeck_token)
        result = client.get_labels()

        assert result == []
