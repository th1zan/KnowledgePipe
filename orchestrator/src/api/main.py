"""Weekly Digest Orchestrator - Main FastAPI Application.

This is the main entry point for the Weekly Digest orchestrator service.
It combines all API routers and sets up the scheduler for periodic jobs.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.feeds import router as feeds_router
from src.api.health import router as health_router
from src.config import get_settings
from src.database import init_db

logger = structlog.get_logger()

# Global scheduler instance
scheduler: AsyncIOScheduler | None = None


def configure_logging() -> None:
    """Configure structlog for the application."""
    settings = get_settings()

    # Configure structlog
    processors = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.log_format == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def create_scheduler() -> AsyncIOScheduler:
    """Create and configure the job scheduler.

    Returns:
        Configured AsyncIOScheduler instance.
    """
    settings = get_settings()
    sched = AsyncIOScheduler()

    # Import jobs here to avoid circular imports
    from src.jobs.rss_fetcher import run_rss_job
    from src.jobs.weekly_sync import run_weekly_sync

    # RSS fetcher - runs daily at configured hour
    sched.add_job(
        run_rss_job,
        CronTrigger(hour=settings.rss_fetch_hour, minute=0),
        id="rss_fetcher",
        name="RSS Feed Fetcher",
        replace_existing=True,
    )

    # Weekly sync - runs weekly on configured day and hour
    day_mapping = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    day_of_week = day_mapping.get(settings.sync_day.lower(), 6)

    sched.add_job(
        run_weekly_sync,
        CronTrigger(day_of_week=day_of_week, hour=settings.sync_hour, minute=0),
        id="weekly_sync",
        name="Weekly Sync",
        replace_existing=True,
    )

    logger.info(
        "scheduler_configured",
        rss_fetch_hour=settings.rss_fetch_hour,
        sync_day=settings.sync_day,
        sync_hour=settings.sync_hour,
    )

    return sched


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup and shutdown.

    Args:
        app: FastAPI application instance.
    """
    global scheduler

    # Startup
    logger.info("application_starting")

    # Initialize database
    init_db()
    logger.info("database_initialized")

    # Start scheduler
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("scheduler_started")

    yield

    # Shutdown
    logger.info("application_stopping")

    if scheduler:
        scheduler.shutdown(wait=False)
        logger.info("scheduler_stopped")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        Configured FastAPI application.
    """
    settings = get_settings()

    # Configure logging
    configure_logging()

    app = FastAPI(
        title="Weekly Digest Orchestrator",
        description="Orchestrates RSS ingestion, weekly sync, and podcast generation",
        version="0.1.0",
        debug=settings.api_debug,
        lifespan=lifespan,
    )

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(health_router)
    app.include_router(feeds_router)

    # Add API routes for manual triggering
    @app.post("/api/sync/trigger", tags=["sync"])
    async def trigger_sync() -> dict[str, Any]:
        """Manually trigger a weekly sync.

        Returns:
            Status message.
        """
        from src.jobs.weekly_sync import run_weekly_sync

        logger.info("manual_sync_triggered")
        run_weekly_sync()
        return {"status": "ok", "message": "Sync triggered"}

    @app.post("/api/rss/fetch", tags=["rss"])
    async def trigger_rss_fetch() -> dict[str, Any]:
        """Manually trigger RSS feed fetching.

        Returns:
            Status message.
        """
        from src.jobs.rss_fetcher import run_rss_job

        logger.info("manual_rss_fetch_triggered")
        result = run_rss_job()
        return {"status": "ok", "result": result}

    @app.get("/api/scheduler/jobs", tags=["scheduler"])
    async def get_scheduled_jobs() -> dict[str, Any]:
        """Get information about scheduled jobs.

        Returns:
            List of scheduled jobs with next run times.
        """
        if scheduler is None:
            return {"status": "not_started", "jobs": []}

        jobs = []
        for job in scheduler.get_jobs():
            jobs.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                }
            )

        return {"status": "ok", "jobs": jobs}

    return app


# Create the app instance
app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "src.api.main:app",
        host="0.0.0.0",
        port=settings.api_port,
        reload=settings.api_debug,
    )
