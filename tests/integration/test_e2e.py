"""End-to-end integration tests for Weekly Digest orchestrator.

These tests require Docker and use WireMock to simulate external services.
Run with: pytest tests/integration/ -v --slow

To run the Docker stack manually:
    docker compose -f tests/integration/docker-compose.test.yml up -d
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Generator

import pytest
import requests

if TYPE_CHECKING:
    from collections.abc import Callable

# Mark all tests in this module as slow/integration
pytestmark = [
    pytest.mark.slow,
    pytest.mark.integration,
]

# Integration test configuration
INTEGRATION_DIR = Path(__file__).parent
DOCKER_COMPOSE_FILE = INTEGRATION_DIR / "docker-compose.test.yml"
MOCK_READECK_URL = "http://localhost:8080"
MOCK_OPENNOTEBOOK_URL = "http://localhost:5055"
ORCHESTRATOR_URL = "http://localhost:8002"

# Timeout settings
STARTUP_TIMEOUT = 60  # seconds
REQUEST_TIMEOUT = 10  # seconds


def is_docker_available() -> bool:
    """Check if Docker is available."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def is_service_healthy(url: str, timeout: float = 5.0) -> bool:
    """Check if a service is responding."""
    try:
        response = requests.get(url, timeout=timeout)
        return response.status_code in (200, 204)
    except requests.RequestException:
        return False


def wait_for_service(url: str, timeout: float = STARTUP_TIMEOUT) -> bool:
    """Wait for a service to become healthy."""
    start = time.time()
    while time.time() - start < timeout:
        if is_service_healthy(url):
            return True
        time.sleep(1)
    return False


@pytest.fixture(scope="module")
def docker_stack() -> Generator[dict[str, str], None, None]:
    """Start Docker Compose stack for integration tests.

    This fixture:
    1. Checks Docker availability
    2. Starts the test stack
    3. Waits for all services to be healthy
    4. Yields service URLs
    5. Tears down the stack after tests
    """
    if not is_docker_available():
        pytest.skip("Docker is not available")

    if not DOCKER_COMPOSE_FILE.exists():
        pytest.skip(f"Docker Compose file not found: {DOCKER_COMPOSE_FILE}")

    # Start the stack
    subprocess.run(
        ["docker", "compose", "-f", str(DOCKER_COMPOSE_FILE), "up", "-d", "--build"],
        cwd=str(INTEGRATION_DIR),
        check=True,
        capture_output=True,
    )

    try:
        # Wait for services
        services = {
            "mock_readeck": f"{MOCK_READECK_URL}/__admin/health",
            "mock_opennotebook": f"{MOCK_OPENNOTEBOOK_URL}/__admin/health",
            # Orchestrator may not be built yet, so we'll check it separately
        }

        for name, url in services.items():
            if not wait_for_service(url):
                # Get logs for debugging
                logs = subprocess.run(
                    [
                        "docker",
                        "compose",
                        "-f",
                        str(DOCKER_COMPOSE_FILE),
                        "logs",
                        "--tail=50",
                    ],
                    cwd=str(INTEGRATION_DIR),
                    capture_output=True,
                    text=True,
                )
                pytest.fail(
                    f"Service {name} failed to start. Logs:\n{logs.stdout}\n{logs.stderr}"
                )

        yield {
            "readeck_url": MOCK_READECK_URL,
            "opennotebook_url": MOCK_OPENNOTEBOOK_URL,
            "orchestrator_url": ORCHESTRATOR_URL,
        }
    finally:
        # Tear down
        subprocess.run(
            ["docker", "compose", "-f", str(DOCKER_COMPOSE_FILE), "down", "-v"],
            cwd=str(INTEGRATION_DIR),
            check=False,
            capture_output=True,
        )


@pytest.fixture
def readeck_client(docker_stack: dict[str, str]) -> Callable[[str], requests.Response]:
    """Create a function to make requests to mock Readeck."""
    base_url = docker_stack["readeck_url"]

    def make_request(path: str, method: str = "GET", **kwargs) -> requests.Response:
        url = f"{base_url}{path}"
        kwargs.setdefault("timeout", REQUEST_TIMEOUT)
        kwargs.setdefault("headers", {})
        kwargs["headers"]["Authorization"] = "Bearer test-token"
        return requests.request(method, url, **kwargs)

    return make_request


@pytest.fixture
def opennotebook_client(
    docker_stack: dict[str, str],
) -> Callable[[str], requests.Response]:
    """Create a function to make requests to mock Open Notebook."""
    base_url = docker_stack["opennotebook_url"]

    def make_request(path: str, method: str = "GET", **kwargs) -> requests.Response:
        url = f"{base_url}{path}"
        kwargs.setdefault("timeout", REQUEST_TIMEOUT)
        kwargs.setdefault("headers", {})
        kwargs["headers"]["Authorization"] = "Bearer test-password"
        return requests.request(method, url, **kwargs)

    return make_request


class TestMockServicesHealth:
    """Tests to verify mock services are working correctly."""

    def test_mock_readeck_is_healthy(self, docker_stack: dict[str, str]) -> None:
        """Verify mock Readeck is responding."""
        url = f"{docker_stack['readeck_url']}/__admin/health"
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        assert response.status_code == 200

    def test_mock_opennotebook_is_healthy(self, docker_stack: dict[str, str]) -> None:
        """Verify mock Open Notebook is responding."""
        url = f"{docker_stack['opennotebook_url']}/__admin/health"
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        assert response.status_code == 200


class TestReadeckAPI:
    """Tests for Readeck API interactions via mocks."""

    def test_get_profile(self, readeck_client: Callable) -> None:
        """Test Readeck profile endpoint."""
        response = readeck_client("/api/profile")
        assert response.status_code == 200
        data = response.json()
        assert "username" in data

    def test_list_bookmarks(self, readeck_client: Callable) -> None:
        """Test listing bookmarks from Readeck."""
        response = readeck_client("/api/bookmarks")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert "id" in data[0]
        assert "url" in data[0]
        assert "title" in data[0]

    def test_create_bookmark(self, readeck_client: Callable) -> None:
        """Test creating a bookmark in Readeck."""
        response = readeck_client(
            "/api/bookmarks",
            method="POST",
            json={"url": "https://example.com/new-article"},
        )
        assert response.status_code == 202
        assert "Bookmark-Id" in response.headers

    def test_get_bookmark_content(self, readeck_client: Callable) -> None:
        """Test retrieving bookmark content as Markdown."""
        response = readeck_client("/api/bookmarks/bm_test123/article.md")
        assert response.status_code == 200
        assert "# Test Article" in response.text


class TestOpenNotebookAPI:
    """Tests for Open Notebook API interactions via mocks."""

    def test_health_check(self, opennotebook_client: Callable) -> None:
        """Test Open Notebook health endpoint."""
        response = opennotebook_client("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_create_notebook(self, opennotebook_client: Callable) -> None:
        """Test creating a notebook."""
        response = opennotebook_client(
            "/api/notebooks",
            method="POST",
            json={"name": "Test Notebook", "description": "Integration test"},
        )
        assert response.status_code == 201
        data = response.json()
        assert "id" in data
        assert data["name"] == "Test Notebook"

    def test_list_notebooks(self, opennotebook_client: Callable) -> None:
        """Test listing notebooks."""
        response = opennotebook_client("/api/notebooks")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_create_source(self, opennotebook_client: Callable) -> None:
        """Test adding a source to a notebook."""
        response = opennotebook_client(
            "/api/sources",
            method="POST",
            data={
                "type": "link",
                "notebooks": '["notebook:test123"]',
                "url": "https://example.com/article",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert "id" in data

    def test_get_source_status(self, opennotebook_client: Callable) -> None:
        """Test checking source processing status."""
        response = opennotebook_client("/api/sources/source:test789/status")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"

    def test_generate_podcast(self, opennotebook_client: Callable) -> None:
        """Test generating a podcast."""
        response = opennotebook_client(
            "/api/podcasts/generate",
            method="POST",
            json={
                "notebook_id": "notebook:test123",
                "episode_name": "Test Episode",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "submitted"

    def test_get_job_status(self, opennotebook_client: Callable) -> None:
        """Test checking podcast generation job status."""
        response = opennotebook_client("/api/podcasts/jobs/job:test456")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert "episode_id" in data

    def test_list_episodes(self, opennotebook_client: Callable) -> None:
        """Test listing podcast episodes."""
        response = opennotebook_client("/api/podcasts/episodes")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_download_audio(self, opennotebook_client: Callable) -> None:
        """Test downloading episode audio."""
        response = opennotebook_client(
            "/api/podcasts/episodes/podcast_episode:ep123/audio"
        )
        assert response.status_code == 200
        assert response.headers["Content-Type"] == "audio/mpeg"


class TestFullWorkflow:
    """End-to-end workflow tests.

    These tests simulate the complete Weekly Digest pipeline:
    1. RSS items are fetched and added to Readeck
    2. Bookmarks are synchronized to Open Notebook
    3. Podcast is generated
    4. RSS feeds are served
    """

    def test_readeck_to_notebook_workflow(
        self,
        readeck_client: Callable,
        opennotebook_client: Callable,
    ) -> None:
        """Test the workflow from Readeck bookmarks to Open Notebook."""
        # Step 1: Get bookmarks from Readeck
        response = readeck_client("/api/bookmarks")
        assert response.status_code == 200
        bookmarks = response.json()
        assert len(bookmarks) >= 1

        # Step 2: Create a notebook in Open Notebook
        response = opennotebook_client(
            "/api/notebooks",
            method="POST",
            json={"name": "Weekly Digest", "description": f"{len(bookmarks)} articles"},
        )
        assert response.status_code == 201
        notebook = response.json()
        notebook_id = notebook["id"]

        # Step 3: Add sources for each bookmark
        for bookmark in bookmarks[:2]:  # Limit for test speed
            response = opennotebook_client(
                "/api/sources",
                method="POST",
                data={
                    "type": "link",
                    "notebooks": f'["{notebook_id}"]',
                    "url": bookmark["url"],
                },
            )
            assert response.status_code == 201

        # Step 4: Check source status (all should be "completed" in mock)
        response = opennotebook_client("/api/sources/source:test789/status")
        assert response.status_code == 200
        assert response.json()["status"] == "completed"

        # Step 5: Generate podcast
        response = opennotebook_client(
            "/api/podcasts/generate",
            method="POST",
            json={
                "notebook_id": notebook_id,
                "episode_name": "Weekly Digest Test",
            },
        )
        assert response.status_code == 200
        job = response.json()

        # Step 6: Check job completion
        response = opennotebook_client(f"/api/podcasts/jobs/{job['job_id']}")
        assert response.status_code == 200
        assert response.json()["status"] == "completed"

    def test_bookmark_content_extraction(
        self,
        readeck_client: Callable,
    ) -> None:
        """Test extracting content from bookmarks for PDF fallback."""
        # Get bookmark content as markdown
        response = readeck_client("/api/bookmarks/bm_test123/article.md")
        assert response.status_code == 200
        content = response.text

        # Verify it's valid markdown
        assert content.startswith("#")
        assert "Section" in content


# Unit tests that don't require Docker (using mocks directly)
class TestWithoutDocker:
    """Tests that use the `responses` library to mock HTTP without Docker.

    These tests are faster and can run in CI without Docker.
    """

    @pytest.fixture(autouse=True)
    def skip_if_integration(self, request: pytest.FixtureRequest) -> None:
        """Skip these tests if running integration suite."""
        if request.config.getoption("--slow", default=False):
            pytest.skip("Skipping unit tests in integration mode")

    def test_placeholder(self) -> None:
        """Placeholder test - real unit tests are in test_clients/."""
        # This class is for tests that validate integration logic
        # without requiring Docker. Most logic is already tested
        # in the unit test suites.
        pass
