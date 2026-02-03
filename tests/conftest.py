"""Pytest fixtures and configuration."""

from __future__ import annotations

import pytest


@pytest.fixture
def readeck_base_url() -> str:
    """Return test Readeck URL."""
    return "http://readeck-test:8000"


@pytest.fixture
def readeck_token() -> str:
    """Return test Readeck token."""
    return "test-token-12345"


@pytest.fixture
def opennotebook_base_url() -> str:
    """Return test Open Notebook URL."""
    return "http://opennotebook-test:5055"


@pytest.fixture
def opennotebook_password() -> str:
    """Return test Open Notebook password."""
    return "test-password"


@pytest.fixture
def sample_bookmark() -> dict:
    """Return a sample bookmark response."""
    return {
        "id": "bm_abc123",
        "url": "https://example.com/article",
        "title": "Test Article",
        "site_name": "Example",
        "site": "example.com",
        "authors": ["John Doe"],
        "published": "2024-01-10T08:00:00Z",
        "created": "2024-01-15T10:30:00Z",
        "type": "article",
        "has_article": True,
        "description": "A test article description",
        "is_marked": False,
        "is_archived": False,
        "labels": ["tech", "test"],
        "word_count": 1500,
        "reading_time": 6,
        "resources": {
            "article": {"src": "/api/bookmarks/bm_abc123/article"},
            "image": {"src": "/api/bookmarks/bm_abc123/image"},
        },
    }


@pytest.fixture
def sample_notebook() -> dict:
    """Return a sample notebook response."""
    return {
        "id": "notebook:abc123",
        "name": "Test Notebook",
        "description": "A test notebook",
        "archived": False,
        "created": "2024-01-15T10:00:00Z",
        "updated": "2024-01-15T10:00:00Z",
        "source_count": 0,
        "note_count": 0,
    }


@pytest.fixture
def sample_source() -> dict:
    """Return a sample source response."""
    return {
        "id": "source:xyz789",
        "title": "Test Source",
        "status": "completed",
        "command_id": "command:cmd123",
    }


@pytest.fixture
def sample_podcast_job() -> dict:
    """Return a sample podcast job response."""
    return {
        "job_id": "job:abc123",
        "status": "submitted",
        "message": "Podcast generation started",
        "episode_profile": "default",
        "episode_name": "Test Episode",
    }


@pytest.fixture
def sample_episode() -> dict:
    """Return a sample episode response."""
    return {
        "id": "podcast_episode:xyz",
        "name": "Test Episode",
        "notebook_id": "notebook:abc123",
        "created": "2024-01-15T12:00:00Z",
        "duration": 300,
    }
