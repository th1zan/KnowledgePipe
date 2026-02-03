"""Health check API endpoints.

This module provides endpoints for monitoring the health
of the orchestrator and its dependencies.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter
from sqlalchemy import text

from src.clients import OpenNotebookClient, ReadeckClient
from src.config import get_settings
from src.database import get_session

logger = structlog.get_logger()

router = APIRouter(tags=["health"])

# Track startup time for uptime calculation
_start_time = datetime.now(timezone.utc)


def get_uptime_seconds() -> int:
    """Get the uptime in seconds since the service started.

    Returns:
        Number of seconds since startup.
    """
    delta = datetime.now(timezone.utc) - _start_time
    return int(delta.total_seconds())


def check_database_health() -> dict[str, Any]:
    """Check database connectivity and health.

    Returns:
        Health status dict with status and optional latency.
    """
    start = time.time()
    try:
        with get_session() as session:
            # Simple query to verify connection
            session.execute(text("SELECT 1"))
        latency_ms = int((time.time() - start) * 1000)
        return {"status": "ok", "latency_ms": latency_ms}
    except Exception as e:
        logger.warning("database_health_check_failed", error=str(e))
        return {"status": "unhealthy", "error": str(e)}


def check_readeck_health() -> dict[str, Any]:
    """Check Readeck API connectivity.

    Returns:
        Health status dict with status and latency.
    """
    settings = get_settings()

    if not settings.readeck_token:
        return {"status": "unconfigured"}

    start = time.time()
    try:
        client = ReadeckClient(
            base_url=settings.readeck_url,
            token=settings.readeck_token,
        )
        healthy = client.health_check()
        latency_ms = int((time.time() - start) * 1000)

        if healthy:
            return {"status": "ok", "latency_ms": latency_ms}
        else:
            return {"status": "unhealthy", "latency_ms": latency_ms}
    except Exception as e:
        latency_ms = int((time.time() - start) * 1000)
        logger.warning("readeck_health_check_failed", error=str(e))
        return {"status": "unhealthy", "latency_ms": latency_ms, "error": str(e)}


def check_opennotebook_health() -> dict[str, Any]:
    """Check Open Notebook API connectivity.

    Returns:
        Health status dict with status and latency.
    """
    settings = get_settings()

    if not settings.open_notebook_password:
        return {"status": "unconfigured"}

    start = time.time()
    try:
        client = OpenNotebookClient(
            base_url=settings.open_notebook_url,
            password=settings.open_notebook_password,
        )
        healthy = client.health_check()
        latency_ms = int((time.time() - start) * 1000)

        if healthy:
            return {"status": "ok", "latency_ms": latency_ms}
        else:
            return {"status": "unhealthy", "latency_ms": latency_ms}
    except Exception as e:
        latency_ms = int((time.time() - start) * 1000)
        logger.warning("opennotebook_health_check_failed", error=str(e))
        return {"status": "unhealthy", "latency_ms": latency_ms, "error": str(e)}


def determine_overall_status(services: dict[str, dict[str, Any]]) -> str:
    """Determine overall health status based on service statuses.

    Args:
        services: Dict of service name to health status.

    Returns:
        "ok" if all services healthy,
        "degraded" if some services unhealthy,
        "unhealthy" if critical services are down.
    """
    statuses = [s.get("status") for s in services.values()]

    # If all services are ok or unconfigured, we're ok
    if all(s in ("ok", "unconfigured") for s in statuses):
        return "ok"

    # If database is down, we're unhealthy
    if services.get("database", {}).get("status") == "unhealthy":
        return "unhealthy"

    # Otherwise we're degraded
    return "degraded"


@router.get("/health")
async def health_basic() -> dict[str, str]:
    """Basic health check endpoint.

    Returns a simple status indicating the service is running.

    Returns:
        Simple status dict.
    """
    return {"status": "ok"}


@router.get("/health/detailed")
async def health_detailed() -> dict[str, Any]:
    """Detailed health check endpoint.

    Checks connectivity to all dependencies and returns
    detailed status information.

    Returns:
        Detailed health status with service information.
    """
    services = {
        "database": check_database_health(),
        "readeck": check_readeck_health(),
        "opennotebook": check_opennotebook_health(),
    }

    overall_status = determine_overall_status(services)

    return {
        "status": overall_status,
        "services": services,
        "uptime_seconds": get_uptime_seconds(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/health/readiness")
async def health_readiness() -> dict[str, Any]:
    """Readiness probe for Kubernetes.

    Checks if the service is ready to accept traffic.

    Returns:
        Readiness status.
    """
    db_health = check_database_health()

    if db_health["status"] == "ok":
        return {"status": "ready"}
    else:
        return {"status": "not_ready", "reason": "database unavailable"}


@router.get("/health/liveness")
async def health_liveness() -> dict[str, str]:
    """Liveness probe for Kubernetes.

    Simple check that the service is alive.

    Returns:
        Liveness status.
    """
    return {"status": "alive"}
