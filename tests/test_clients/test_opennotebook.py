"""Tests for Open Notebook client."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import responses
from requests.exceptions import ConnectionError as RequestsConnectionError
from responses import matchers

from src.clients.opennotebook import OpenNotebookClient, OpenNotebookError


class TestOpenNotebookHealthCheck:
    """Tests for health_check method."""

    @responses.activate
    def test_health_check_success(
        self,
        opennotebook_base_url: str,
        opennotebook_password: str,
    ):
        """Test successful health check."""
        responses.add(
            responses.GET,
            f"{opennotebook_base_url}/health",
            json={"status": "ok"},
            status=200,
        )

        client = OpenNotebookClient(opennotebook_base_url, opennotebook_password)
        assert client.health_check() is True

    @responses.activate
    def test_health_check_failure(
        self,
        opennotebook_base_url: str,
        opennotebook_password: str,
    ):
        """Test health check when server is down."""
        responses.add(
            responses.GET,
            f"{opennotebook_base_url}/health",
            body=RequestsConnectionError("Connection refused"),
        )

        client = OpenNotebookClient(opennotebook_base_url, opennotebook_password)
        assert client.health_check() is False


class TestOpenNotebookNotebooks:
    """Tests for notebook-related methods."""

    @responses.activate
    def test_create_notebook(
        self,
        opennotebook_base_url: str,
        opennotebook_password: str,
        sample_notebook: dict,
    ):
        """Test creating a notebook."""
        responses.add(
            responses.POST,
            f"{opennotebook_base_url}/api/notebooks",
            json=sample_notebook,
            status=201,
        )

        client = OpenNotebookClient(opennotebook_base_url, opennotebook_password)
        result = client.create_notebook("Test Notebook", "A test notebook")

        assert result["id"] == "notebook:abc123"
        assert result["name"] == "Test Notebook"

    @responses.activate
    def test_create_notebook_failure(
        self,
        opennotebook_base_url: str,
        opennotebook_password: str,
    ):
        """Test notebook creation failure."""
        responses.add(
            responses.POST,
            f"{opennotebook_base_url}/api/notebooks",
            json={"error": "Invalid request"},
            status=400,
        )

        client = OpenNotebookClient(opennotebook_base_url, opennotebook_password)

        with pytest.raises(OpenNotebookError):
            client.create_notebook("Test", "Test")

    @responses.activate
    def test_get_notebook(
        self,
        opennotebook_base_url: str,
        opennotebook_password: str,
        sample_notebook: dict,
    ):
        """Test getting a notebook by ID."""
        responses.add(
            responses.GET,
            f"{opennotebook_base_url}/api/notebooks/notebook:abc123",
            json=sample_notebook,
            status=200,
        )

        client = OpenNotebookClient(opennotebook_base_url, opennotebook_password)
        result = client.get_notebook("notebook:abc123")

        assert result is not None
        assert result["id"] == "notebook:abc123"

    @responses.activate
    def test_get_notebook_not_found(
        self,
        opennotebook_base_url: str,
        opennotebook_password: str,
    ):
        """Test getting non-existent notebook."""
        responses.add(
            responses.GET,
            f"{opennotebook_base_url}/api/notebooks/notebook:notfound",
            status=404,
        )

        client = OpenNotebookClient(opennotebook_base_url, opennotebook_password)
        result = client.get_notebook("notebook:notfound")

        assert result is None

    @responses.activate
    def test_list_notebooks(
        self,
        opennotebook_base_url: str,
        opennotebook_password: str,
        sample_notebook: dict,
    ):
        """Test listing notebooks."""
        responses.add(
            responses.GET,
            f"{opennotebook_base_url}/api/notebooks",
            json=[sample_notebook],
            status=200,
        )

        client = OpenNotebookClient(opennotebook_base_url, opennotebook_password)
        result = client.list_notebooks()

        assert len(result) == 1
        assert result[0]["id"] == "notebook:abc123"


class TestOpenNotebookSources:
    """Tests for source-related methods."""

    @responses.activate
    def test_add_source_url(
        self,
        opennotebook_base_url: str,
        opennotebook_password: str,
        sample_source: dict,
    ):
        """Test adding a URL source."""
        responses.add(
            responses.POST,
            f"{opennotebook_base_url}/api/sources",
            json=sample_source,
            status=201,
        )

        client = OpenNotebookClient(opennotebook_base_url, opennotebook_password)
        result = client.add_source_url("notebook:abc123", "https://example.com/article")

        assert result["id"] == "source:xyz789"

    @responses.activate
    def test_add_source_text(
        self,
        opennotebook_base_url: str,
        opennotebook_password: str,
        sample_source: dict,
    ):
        """Test adding a text source."""
        responses.add(
            responses.POST,
            f"{opennotebook_base_url}/api/sources",
            json=sample_source,
            status=201,
        )

        client = OpenNotebookClient(opennotebook_base_url, opennotebook_password)
        result = client.add_source_text(
            "notebook:abc123",
            "This is the content",
            "Test Document",
        )

        assert result["id"] == "source:xyz789"

    @responses.activate
    def test_get_source_status_completed(
        self,
        opennotebook_base_url: str,
        opennotebook_password: str,
    ):
        """Test getting source status when completed."""
        responses.add(
            responses.GET,
            f"{opennotebook_base_url}/api/sources/source:xyz789/status",
            json={"status": "completed"},
            status=200,
        )

        client = OpenNotebookClient(opennotebook_base_url, opennotebook_password)
        result = client.get_source_status("source:xyz789")

        assert result["status"] == "completed"

    @responses.activate
    def test_wait_for_source_success(
        self,
        opennotebook_base_url: str,
        opennotebook_password: str,
    ):
        """Test waiting for source processing to complete."""
        # First call returns processing, second returns completed
        responses.add(
            responses.GET,
            f"{opennotebook_base_url}/api/sources/source:xyz789/status",
            json={"status": "processing"},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{opennotebook_base_url}/api/sources/source:xyz789/status",
            json={"status": "completed"},
            status=200,
        )

        client = OpenNotebookClient(opennotebook_base_url, opennotebook_password)

        with patch("time.sleep"):  # Skip actual waiting
            result = client.wait_for_source(
                "source:xyz789", timeout=60, poll_interval=1
            )

        assert result is True

    @responses.activate
    def test_wait_for_source_timeout(
        self,
        opennotebook_base_url: str,
        opennotebook_password: str,
    ):
        """Test source processing timeout."""
        # Always returns processing - add multiple responses for retries
        for _ in range(10):
            responses.add(
                responses.GET,
                f"{opennotebook_base_url}/api/sources/source:xyz789/status",
                json={"status": "processing"},
                status=200,
            )

        client = OpenNotebookClient(opennotebook_base_url, opennotebook_password)

        # Use very short timeout to make test fast
        result = client.wait_for_source(
            "source:xyz789", timeout=0.1, poll_interval=0.01
        )

        assert result is False

    @responses.activate
    def test_wait_for_source_failed(
        self,
        opennotebook_base_url: str,
        opennotebook_password: str,
    ):
        """Test source processing failure."""
        responses.add(
            responses.GET,
            f"{opennotebook_base_url}/api/sources/source:xyz789/status",
            json={"status": "failed"},
            status=200,
        )

        client = OpenNotebookClient(opennotebook_base_url, opennotebook_password)
        result = client.wait_for_source("source:xyz789")

        assert result is False


class TestOpenNotebookPodcasts:
    """Tests for podcast-related methods."""

    @responses.activate
    def test_generate_podcast(
        self,
        opennotebook_base_url: str,
        opennotebook_password: str,
        sample_podcast_job: dict,
    ):
        """Test starting podcast generation."""
        responses.add(
            responses.POST,
            f"{opennotebook_base_url}/api/podcasts/generate",
            json=sample_podcast_job,
            status=202,
        )

        client = OpenNotebookClient(opennotebook_base_url, opennotebook_password)
        result = client.generate_podcast("notebook:abc123", "Test Episode")

        assert result["job_id"] == "job:abc123"
        assert result["status"] == "submitted"

    @responses.activate
    def test_get_podcast_job_status(
        self,
        opennotebook_base_url: str,
        opennotebook_password: str,
    ):
        """Test getting podcast job status."""
        responses.add(
            responses.GET,
            f"{opennotebook_base_url}/api/podcasts/jobs/job:abc123",
            json={
                "job_id": "job:abc123",
                "status": "completed",
                "episode_id": "ep:xyz",
            },
            status=200,
        )

        client = OpenNotebookClient(opennotebook_base_url, opennotebook_password)
        result = client.get_podcast_job_status("job:abc123")

        assert result["status"] == "completed"
        assert result["episode_id"] == "ep:xyz"

    @responses.activate
    def test_wait_for_podcast_success(
        self,
        opennotebook_base_url: str,
        opennotebook_password: str,
    ):
        """Test waiting for podcast generation."""
        responses.add(
            responses.GET,
            f"{opennotebook_base_url}/api/podcasts/jobs/job:abc123",
            json={"status": "processing"},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{opennotebook_base_url}/api/podcasts/jobs/job:abc123",
            json={"status": "completed", "episode_id": "podcast_episode:xyz"},
            status=200,
        )

        client = OpenNotebookClient(opennotebook_base_url, opennotebook_password)

        with patch("time.sleep"):
            result = client.wait_for_podcast("job:abc123", timeout=120, poll_interval=1)

        assert result == "podcast_episode:xyz"

    @responses.activate
    def test_download_audio(
        self,
        opennotebook_base_url: str,
        opennotebook_password: str,
    ):
        """Test downloading episode audio."""
        audio_data = b"fake mp3 data here"
        responses.add(
            responses.GET,
            f"{opennotebook_base_url}/api/podcasts/episodes/podcast_episode:xyz/audio",
            body=audio_data,
            status=200,
            content_type="audio/mpeg",
        )

        client = OpenNotebookClient(opennotebook_base_url, opennotebook_password)
        result = client.download_episode_audio("podcast_episode:xyz")

        assert result == audio_data

    @responses.activate
    def test_download_audio_not_found(
        self,
        opennotebook_base_url: str,
        opennotebook_password: str,
    ):
        """Test downloading non-existent audio."""
        responses.add(
            responses.GET,
            f"{opennotebook_base_url}/api/podcasts/episodes/podcast_episode:notfound/audio",
            status=404,
        )

        client = OpenNotebookClient(opennotebook_base_url, opennotebook_password)
        result = client.download_episode_audio("podcast_episode:notfound")

        assert result is None

    @responses.activate
    def test_list_episodes(
        self,
        opennotebook_base_url: str,
        opennotebook_password: str,
        sample_episode: dict,
    ):
        """Test listing episodes."""
        responses.add(
            responses.GET,
            f"{opennotebook_base_url}/api/podcasts/episodes",
            json=[sample_episode],
            status=200,
        )

        client = OpenNotebookClient(opennotebook_base_url, opennotebook_password)
        result = client.list_episodes()

        assert len(result) == 1
        assert result[0]["id"] == "podcast_episode:xyz"


class TestOpenNotebookNotes:
    """Tests for notes-related methods."""

    @responses.activate
    def test_get_notebook_notes(
        self,
        opennotebook_base_url: str,
        opennotebook_password: str,
    ):
        """Test getting notes for a notebook."""
        notes = [
            {"id": "note:1", "title": "Summary", "content": "This is a summary"},
        ]
        responses.add(
            responses.GET,
            f"{opennotebook_base_url}/api/notes",
            json=notes,
            status=200,
        )

        client = OpenNotebookClient(opennotebook_base_url, opennotebook_password)
        result = client.get_notebook_notes("notebook:abc123")

        assert len(result) == 1
        assert result[0]["title"] == "Summary"

    @responses.activate
    def test_create_note(
        self,
        opennotebook_base_url: str,
        opennotebook_password: str,
    ):
        """Test creating a note."""
        note = {"id": "note:new", "title": "Test Note", "content": "Content"}
        responses.add(
            responses.POST,
            f"{opennotebook_base_url}/api/notes",
            json=note,
            status=201,
        )

        client = OpenNotebookClient(opennotebook_base_url, opennotebook_password)
        result = client.create_note("notebook:abc123", "Test Note", "Content")

        assert result["id"] == "note:new"


class TestOpenNotebookTransformations:
    """Tests for transformation-related methods."""

    @responses.activate
    def test_apply_transformation(
        self,
        opennotebook_base_url: str,
        opennotebook_password: str,
    ):
        """Test applying a transformation to a source."""
        responses.add(
            responses.POST,
            f"{opennotebook_base_url}/api/sources/source:xyz/insights",
            json={"insight_id": "insight:123"},
            status=201,
        )

        client = OpenNotebookClient(opennotebook_base_url, opennotebook_password)
        result = client.apply_transformation("source:xyz", "transformation:summary")

        assert "insight_id" in result

    @responses.activate
    def test_list_transformations(
        self,
        opennotebook_base_url: str,
        opennotebook_password: str,
    ):
        """Test listing available transformations."""
        transformations = [
            {
                "id": "transformation:summary",
                "name": "Summary",
                "title": "Generate Summary",
            },
        ]
        responses.add(
            responses.GET,
            f"{opennotebook_base_url}/api/transformations",
            json=transformations,
            status=200,
        )

        client = OpenNotebookClient(opennotebook_base_url, opennotebook_password)
        result = client.list_transformations()

        assert len(result) == 1
        assert result[0]["name"] == "Summary"
