"""Tests for the health check API."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from src.api.health import (
    check_database_health,
    check_opennotebook_health,
    check_readeck_health,
    determine_overall_status,
    get_uptime_seconds,
    router,
)
from src.database import Base, reset_engine, set_engine

# Create a minimal FastAPI app for testing
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
        yield db_path
        reset_engine()


class TestUptimeSeconds:
    """Tests for uptime calculation."""

    def test_get_uptime_seconds(self):
        """Test that uptime is a positive integer."""
        uptime = get_uptime_seconds()
        assert isinstance(uptime, int)
        assert uptime >= 0


class TestDetermineOverallStatus:
    """Tests for overall status determination."""

    def test_all_healthy(self):
        """Test status when all services are healthy."""
        services = {
            "database": {"status": "ok"},
            "readeck": {"status": "ok"},
            "opennotebook": {"status": "ok"},
        }
        assert determine_overall_status(services) == "ok"

    def test_some_unconfigured(self):
        """Test status when some services are unconfigured."""
        services = {
            "database": {"status": "ok"},
            "readeck": {"status": "unconfigured"},
            "opennotebook": {"status": "ok"},
        }
        assert determine_overall_status(services) == "ok"

    def test_database_unhealthy(self):
        """Test status when database is unhealthy (critical)."""
        services = {
            "database": {"status": "unhealthy"},
            "readeck": {"status": "ok"},
            "opennotebook": {"status": "ok"},
        }
        assert determine_overall_status(services) == "unhealthy"

    def test_external_service_unhealthy(self):
        """Test status when external service is unhealthy (degraded)."""
        services = {
            "database": {"status": "ok"},
            "readeck": {"status": "unhealthy"},
            "opennotebook": {"status": "ok"},
        }
        assert determine_overall_status(services) == "degraded"

    def test_all_external_unhealthy(self):
        """Test status when all external services are unhealthy."""
        services = {
            "database": {"status": "ok"},
            "readeck": {"status": "unhealthy"},
            "opennotebook": {"status": "unhealthy"},
        }
        assert determine_overall_status(services) == "degraded"


class TestCheckDatabaseHealth:
    """Tests for database health check."""

    def test_check_database_health_success(self, temp_db: Path):
        """Test database health check when healthy."""
        result = check_database_health()

        assert result["status"] == "ok"
        assert "latency_ms" in result
        assert isinstance(result["latency_ms"], int)

    def test_check_database_health_failure(self):
        """Test database health check when unhealthy."""
        # Reset engine to break the connection
        reset_engine()

        with patch("src.api.health.get_session") as mock_session:
            mock_session.side_effect = Exception("Connection failed")

            result = check_database_health()

        assert result["status"] == "unhealthy"
        assert "error" in result


class TestCheckReadeckHealth:
    """Tests for Readeck health check."""

    def test_check_readeck_unconfigured(self):
        """Test Readeck health when not configured."""
        with patch("src.api.health.get_settings") as mock_settings:
            mock_settings.return_value.readeck_token = ""

            result = check_readeck_health()

        assert result["status"] == "unconfigured"

    def test_check_readeck_healthy(self):
        """Test Readeck health when healthy."""
        with patch("src.api.health.get_settings") as mock_settings:
            mock_settings.return_value.readeck_token = "token"
            mock_settings.return_value.readeck_url = "http://readeck:8000"

            with patch("src.api.health.ReadeckClient") as MockClient:
                MockClient.return_value.health_check.return_value = True

                result = check_readeck_health()

        assert result["status"] == "ok"
        assert "latency_ms" in result

    def test_check_readeck_unhealthy(self):
        """Test Readeck health when unhealthy."""
        with patch("src.api.health.get_settings") as mock_settings:
            mock_settings.return_value.readeck_token = "token"
            mock_settings.return_value.readeck_url = "http://readeck:8000"

            with patch("src.api.health.ReadeckClient") as MockClient:
                MockClient.return_value.health_check.return_value = False

                result = check_readeck_health()

        assert result["status"] == "unhealthy"

    def test_check_readeck_exception(self):
        """Test Readeck health when exception occurs."""
        with patch("src.api.health.get_settings") as mock_settings:
            mock_settings.return_value.readeck_token = "token"
            mock_settings.return_value.readeck_url = "http://readeck:8000"

            with patch("src.api.health.ReadeckClient") as MockClient:
                MockClient.return_value.health_check.side_effect = Exception("Timeout")

                result = check_readeck_health()

        assert result["status"] == "unhealthy"
        assert "error" in result


class TestCheckOpenNotebookHealth:
    """Tests for Open Notebook health check."""

    def test_check_opennotebook_unconfigured(self):
        """Test Open Notebook health when not configured."""
        with patch("src.api.health.get_settings") as mock_settings:
            mock_settings.return_value.open_notebook_password = ""

            result = check_opennotebook_health()

        assert result["status"] == "unconfigured"

    def test_check_opennotebook_healthy(self):
        """Test Open Notebook health when healthy."""
        with patch("src.api.health.get_settings") as mock_settings:
            mock_settings.return_value.open_notebook_password = "pass"
            mock_settings.return_value.open_notebook_url = "http://on:5055"

            with patch("src.api.health.OpenNotebookClient") as MockClient:
                MockClient.return_value.health_check.return_value = True

                result = check_opennotebook_health()

        assert result["status"] == "ok"
        assert "latency_ms" in result

    def test_check_opennotebook_unhealthy(self):
        """Test Open Notebook health when unhealthy."""
        with patch("src.api.health.get_settings") as mock_settings:
            mock_settings.return_value.open_notebook_password = "pass"
            mock_settings.return_value.open_notebook_url = "http://on:5055"

            with patch("src.api.health.OpenNotebookClient") as MockClient:
                MockClient.return_value.health_check.return_value = False

                result = check_opennotebook_health()

        assert result["status"] == "unhealthy"


class TestHealthEndpoints:
    """Tests for health API endpoints."""

    def test_health_basic(self):
        """Test GET /health endpoint."""
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_health_detailed(self, temp_db: Path):
        """Test GET /health/detailed endpoint."""
        with patch("src.api.health.get_settings") as mock_settings:
            mock_settings.return_value.readeck_token = ""
            mock_settings.return_value.open_notebook_password = ""

            response = client.get("/health/detailed")

        assert response.status_code == 200
        data = response.json()

        assert "status" in data
        assert "services" in data
        assert "uptime_seconds" in data
        assert "timestamp" in data
        assert "database" in data["services"]
        assert "readeck" in data["services"]
        assert "opennotebook" in data["services"]

    def test_health_readiness_ready(self, temp_db: Path):
        """Test GET /health/readiness when ready."""
        response = client.get("/health/readiness")

        assert response.status_code == 200
        assert response.json()["status"] == "ready"

    def test_health_readiness_not_ready(self):
        """Test GET /health/readiness when not ready."""
        reset_engine()

        with patch("src.api.health.get_session") as mock_session:
            mock_session.side_effect = Exception("DB unavailable")

            response = client.get("/health/readiness")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "not_ready"
        assert "database" in data["reason"]

    def test_health_liveness(self):
        """Test GET /health/liveness endpoint."""
        response = client.get("/health/liveness")

        assert response.status_code == 200
        assert response.json() == {"status": "alive"}
