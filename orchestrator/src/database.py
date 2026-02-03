"""Database module with SQLAlchemy models and helper functions.

This module provides the database layer for the Weekly Digest orchestrator,
including models for RSS items, sync logs, and podcast episodes.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

from sqlalchemy import Boolean, DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from src.config import get_settings


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass


class RssItem(Base):
    """Model for tracking processed RSS items.

    Attributes:
        id: Primary key.
        guid: Unique identifier from the RSS feed (entry id or link).
        url: URL of the article.
        title: Title of the article.
        feed_url: URL of the RSS feed this item came from.
        bookmark_id: ID of the bookmark created in Readeck.
        created_at: Timestamp when the item was processed.
    """

    __tablename__ = "rss_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guid: Mapped[str] = mapped_column(String(512), unique=True, nullable=False, index=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    feed_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    bookmark_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )


class SyncLog(Base):
    """Model for tracking weekly sync operations.

    Attributes:
        id: Primary key.
        started_at: Timestamp when the sync started.
        completed_at: Timestamp when the sync completed (None if still running).
        status: Current status (pending, running, completed, failed).
        notebook_id: ID of the notebook created in Open Notebook.
        bookmarks_count: Number of bookmarks processed in this sync.
        error: Error message if the sync failed.
    """

    __tablename__ = "sync_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    notebook_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bookmarks_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Episode(Base):
    """Model for tracking generated podcast episodes.

    Attributes:
        id: Primary key.
        notebook_id: ID of the source notebook in Open Notebook.
        episode_id: ID of the episode in Open Notebook.
        episode_name: Human-readable name of the episode.
        audio_url: URL where the audio file is accessible.
        created_at: Timestamp when the episode was created.
        uploaded: Whether the audio has been uploaded to external storage.
        public_url: Public URL after upload to external storage.
    """

    __tablename__ = "episodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    notebook_id: Mapped[str] = mapped_column(String(64), nullable=False)
    episode_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    episode_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    audio_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    uploaded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    public_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)


# Engine and session factory (initialized lazily)
_engine = None
_SessionLocal = None


def _get_engine():
    """Get or create the database engine.

    Returns:
        SQLAlchemy engine instance.
    """
    global _engine
    if _engine is None:
        settings = get_settings()
        db_path = Path(settings.database_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            f"sqlite:///{db_path}",
            echo=False,
            connect_args={"check_same_thread": False},
        )
    return _engine


def _get_session_factory():
    """Get or create the session factory.

    Returns:
        SQLAlchemy sessionmaker instance.
    """
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=_get_engine(), expire_on_commit=False)
    return _SessionLocal


def init_db() -> None:
    """Initialize the database by creating all tables.

    This function is idempotent and safe to call multiple times.
    """
    engine = _get_engine()
    Base.metadata.create_all(engine)


def reset_engine() -> None:
    """Reset the engine and session factory.

    This is primarily useful for testing when switching databases.
    """
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def set_engine(engine) -> None:
    """Set a custom engine (primarily for testing).

    Args:
        engine: SQLAlchemy engine instance to use.
    """
    global _engine, _SessionLocal
    _engine = engine
    _SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Get a database session as a context manager.

    Yields:
        SQLAlchemy Session instance.

    Example:
        with get_session() as session:
            item = session.query(RssItem).first()
    """
    session_factory = _get_session_factory()
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# RSS Item helpers


def is_rss_item_processed(guid: str) -> bool:
    """Check if an RSS item has already been processed.

    Args:
        guid: Unique identifier of the RSS item.

    Returns:
        True if the item has been processed, False otherwise.
    """
    with get_session() as session:
        return session.query(RssItem).filter_by(guid=guid).first() is not None


def add_rss_item(
    guid: str,
    url: str,
    title: str | None,
    feed_url: str,
    bookmark_id: str | None = None,
) -> RssItem:
    """Add a new RSS item to the database.

    Args:
        guid: Unique identifier from the RSS feed.
        url: URL of the article.
        title: Title of the article.
        feed_url: URL of the RSS feed.
        bookmark_id: ID of the bookmark created in Readeck.

    Returns:
        The created RssItem instance.
    """
    with get_session() as session:
        item = RssItem(
            guid=guid,
            url=url,
            title=title,
            feed_url=feed_url,
            bookmark_id=bookmark_id,
        )
        session.add(item)
        session.flush()
        # Refresh to get the generated ID
        session.refresh(item)
        return item


def get_rss_item_by_guid(guid: str) -> RssItem | None:
    """Get an RSS item by its GUID.

    Args:
        guid: Unique identifier of the RSS item.

    Returns:
        The RssItem if found, None otherwise.
    """
    with get_session() as session:
        return session.query(RssItem).filter_by(guid=guid).first()


# Sync Log helpers


def create_sync_log(notebook_id: str | None = None, bookmarks_count: int = 0) -> SyncLog:
    """Create a new sync log entry.

    Args:
        notebook_id: ID of the notebook being created.
        bookmarks_count: Number of bookmarks to process.

    Returns:
        The created SyncLog instance.
    """
    with get_session() as session:
        log = SyncLog(
            status="running",
            notebook_id=notebook_id,
            bookmarks_count=bookmarks_count,
        )
        session.add(log)
        session.flush()
        session.refresh(log)
        return log


def update_sync_log(
    log_id: int,
    status: str,
    error: str | None = None,
    notebook_id: str | None = None,
    bookmarks_count: int | None = None,
) -> SyncLog | None:
    """Update an existing sync log entry.

    Args:
        log_id: ID of the sync log to update.
        status: New status (pending, running, completed, failed).
        error: Error message if the sync failed.
        notebook_id: ID of the notebook (if created after log).
        bookmarks_count: Updated count of bookmarks processed.

    Returns:
        The updated SyncLog if found, None otherwise.
    """
    with get_session() as session:
        log = session.query(SyncLog).filter_by(id=log_id).first()
        if log is None:
            return None

        log.status = status
        if error is not None:
            log.error = error
        if notebook_id is not None:
            log.notebook_id = notebook_id
        if bookmarks_count is not None:
            log.bookmarks_count = bookmarks_count
        if status in ("completed", "failed"):
            log.completed_at = datetime.now(timezone.utc)

        session.flush()
        session.refresh(log)
        return log


def get_latest_sync_logs(limit: int = 10) -> list[SyncLog]:
    """Get the most recent sync logs.

    Args:
        limit: Maximum number of logs to return.

    Returns:
        List of SyncLog instances, ordered by started_at descending.
    """
    with get_session() as session:
        return session.query(SyncLog).order_by(SyncLog.started_at.desc()).limit(limit).all()


# Episode helpers


def add_episode(
    notebook_id: str,
    episode_id: str,
    episode_name: str | None = None,
    audio_url: str | None = None,
) -> Episode:
    """Add a new episode to the database.

    Args:
        notebook_id: ID of the source notebook.
        episode_id: ID of the episode in Open Notebook.
        episode_name: Human-readable name of the episode.
        audio_url: URL where the audio is accessible.

    Returns:
        The created Episode instance.
    """
    with get_session() as session:
        episode = Episode(
            notebook_id=notebook_id,
            episode_id=episode_id,
            episode_name=episode_name,
            audio_url=audio_url,
        )
        session.add(episode)
        session.flush()
        session.refresh(episode)
        return episode


def mark_episode_uploaded(episode_id: str, public_url: str) -> Episode | None:
    """Mark an episode as uploaded and set its public URL.

    Args:
        episode_id: ID of the episode in Open Notebook.
        public_url: Public URL where the audio is accessible.

    Returns:
        The updated Episode if found, None otherwise.
    """
    with get_session() as session:
        episode = session.query(Episode).filter_by(episode_id=episode_id).first()
        if episode is None:
            return None

        episode.uploaded = True
        episode.public_url = public_url
        session.flush()
        session.refresh(episode)
        return episode


def get_episode_by_id(episode_id: str) -> Episode | None:
    """Get an episode by its Open Notebook ID.

    Args:
        episode_id: ID of the episode in Open Notebook.

    Returns:
        The Episode if found, None otherwise.
    """
    with get_session() as session:
        return session.query(Episode).filter_by(episode_id=episode_id).first()


def get_latest_episodes(limit: int = 20) -> list[Episode]:
    """Get the most recent episodes.

    Args:
        limit: Maximum number of episodes to return.

    Returns:
        List of Episode instances, ordered by created_at descending.
    """
    with get_session() as session:
        return session.query(Episode).order_by(Episode.created_at.desc()).limit(limit).all()


def get_uploaded_episodes(limit: int = 20) -> list[Episode]:
    """Get the most recent uploaded episodes.

    Args:
        limit: Maximum number of episodes to return.

    Returns:
        List of uploaded Episode instances, ordered by created_at descending.
    """
    with get_session() as session:
        return (
            session.query(Episode)
            .filter_by(uploaded=True)
            .order_by(Episode.created_at.desc())
            .limit(limit)
            .all()
        )
