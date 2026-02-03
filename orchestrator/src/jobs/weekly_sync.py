"""Weekly sync job.

This module synchronizes Readeck bookmarks to Open Notebook,
creates notebooks, generates summaries and podcasts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import structlog

from src.clients import OpenNotebookClient, ReadeckClient
from src.config import get_settings
from src.database import (
    add_episode,
    create_sync_log,
    update_sync_log,
)

logger = structlog.get_logger()


@dataclass
class Bookmark:
    """Represents a Readeck bookmark.

    Attributes:
        id: Bookmark ID in Readeck.
        url: URL of the bookmarked page.
        title: Title of the bookmark.
        is_pdf: Whether the bookmark is a PDF.
        content: Extracted content (for PDFs).
    """

    id: str
    url: str
    title: str | None
    is_pdf: bool = False
    content: str | None = None


@dataclass
class GenerationResult:
    """Result of content generation.

    Attributes:
        notebook_id: ID of the created notebook.
        episode_id: ID of the generated podcast episode (if any).
        summary: Generated summary text (if any).
        audio_url: URL of the generated audio (if any).
        success: Whether generation was successful.
        error: Error message if generation failed.
    """

    notebook_id: str
    episode_id: str | None = None
    summary: str | None = None
    audio_url: str | None = None
    success: bool = True
    error: str | None = None


@dataclass
class SyncResult:
    """Result of the weekly sync operation.

    Attributes:
        notebook_id: ID of the created notebook.
        bookmarks_count: Number of bookmarks processed.
        sources_added: Number of sources successfully added.
        sources_failed: Number of sources that failed to add.
        episode_id: ID of the generated podcast episode.
        success: Whether the sync was successful overall.
        error: Error message if sync failed.
    """

    notebook_id: str | None
    bookmarks_count: int
    sources_added: int
    sources_failed: int
    episode_id: str | None = None
    success: bool = True
    error: str | None = None


def get_week_bookmarks(
    readeck_client: ReadeckClient | None = None,
) -> list[Bookmark]:
    """Get bookmarks from the past week.

    Args:
        readeck_client: Optional Readeck client. If not provided, creates one.

    Returns:
        List of Bookmark instances.
    """
    settings = get_settings()

    if readeck_client is None:
        readeck_client = ReadeckClient(
            base_url=settings.readeck_url,
            token=settings.readeck_token,
        )

    bookmarks_data = readeck_client.get_week_bookmarks()
    bookmarks = []

    for bm in bookmarks_data:
        is_pdf = bm.get("type") == "pdf" or bm.get("url", "").lower().endswith(".pdf")

        content = None
        if is_pdf:
            # Try to get extracted content for PDFs
            try:
                content = readeck_client.get_bookmark_content(bm["id"], format="md")
            except Exception as e:
                logger.warning(
                    "pdf_content_extraction_failed",
                    bookmark_id=bm["id"],
                    error=str(e),
                )

        bookmarks.append(
            Bookmark(
                id=bm["id"],
                url=bm.get("url", ""),
                title=bm.get("title"),
                is_pdf=is_pdf,
                content=content,
            )
        )

    logger.info("week_bookmarks_retrieved", count=len(bookmarks))
    return bookmarks


def create_weekly_notebook(
    bookmarks: list[Bookmark],
    on_client: OpenNotebookClient | None = None,
    notebook_name: str | None = None,
) -> str:
    """Create a new notebook for the weekly sync.

    Args:
        bookmarks: List of bookmarks to process.
        on_client: Optional Open Notebook client.
        notebook_name: Optional custom name for the notebook.

    Returns:
        The notebook ID.
    """
    settings = get_settings()

    if on_client is None:
        on_client = OpenNotebookClient(
            base_url=settings.open_notebook_url,
            password=settings.open_notebook_password,
        )

    if notebook_name is None:
        notebook_name = f"Semaine du {datetime.now(timezone.utc).strftime('%d/%m/%Y')}"

    description = f"{len(bookmarks)} articles"

    notebook = on_client.create_notebook(name=notebook_name, description=description)
    notebook_id = notebook["id"]

    logger.info("notebook_created", notebook_id=notebook_id, name=notebook_name)
    return notebook_id


def add_sources_to_notebook(
    notebook_id: str,
    bookmarks: list[Bookmark],
    on_client: OpenNotebookClient | None = None,
) -> tuple[list[str], int]:
    """Add bookmarks as sources to a notebook.

    For PDFs with extracted content, adds as text source.
    For regular URLs, adds as URL source.

    Args:
        notebook_id: ID of the target notebook.
        bookmarks: List of bookmarks to add.
        on_client: Optional Open Notebook client.

    Returns:
        Tuple of (list of source IDs, number of failures).
    """
    settings = get_settings()

    if on_client is None:
        on_client = OpenNotebookClient(
            base_url=settings.open_notebook_url,
            password=settings.open_notebook_password,
        )

    source_ids = []
    failures = 0

    for bookmark in bookmarks:
        try:
            if bookmark.is_pdf and bookmark.content:
                # Add PDF content as text source
                source = on_client.add_source_text(
                    notebook_id=notebook_id,
                    content=bookmark.content,
                    title=bookmark.title or "PDF Document",
                    embed=True,
                )
            else:
                # Add as URL source
                source = on_client.add_source_url(
                    notebook_id=notebook_id,
                    url=bookmark.url,
                    embed=True,
                    async_processing=True,
                )

            source_ids.append(source["id"])
            logger.info(
                "source_added",
                source_id=source["id"],
                bookmark_id=bookmark.id,
                title=bookmark.title,
            )

        except Exception as e:
            failures += 1
            logger.error(
                "source_add_failed",
                bookmark_id=bookmark.id,
                url=bookmark.url,
                error=str(e),
            )

    logger.info(
        "sources_added_to_notebook",
        notebook_id=notebook_id,
        added=len(source_ids),
        failed=failures,
    )

    return source_ids, failures


def wait_for_sources(
    source_ids: list[str],
    on_client: OpenNotebookClient | None = None,
    timeout: int | None = None,
) -> tuple[int, int]:
    """Wait for all sources to finish processing.

    Args:
        source_ids: List of source IDs to wait for.
        on_client: Optional Open Notebook client.
        timeout: Optional timeout per source in seconds.

    Returns:
        Tuple of (successful count, failed count).
    """
    settings = get_settings()

    if on_client is None:
        on_client = OpenNotebookClient(
            base_url=settings.open_notebook_url,
            password=settings.open_notebook_password,
        )

    if timeout is None:
        timeout = settings.source_processing_timeout

    success_count = 0
    failed_count = 0

    for source_id in source_ids:
        try:
            if on_client.wait_for_source(source_id, timeout=timeout):
                success_count += 1
                logger.debug("source_processed", source_id=source_id)
            else:
                failed_count += 1
                logger.warning("source_processing_timeout", source_id=source_id)
        except Exception as e:
            failed_count += 1
            logger.error("source_wait_failed", source_id=source_id, error=str(e))

    logger.info(
        "sources_processing_completed",
        success=success_count,
        failed=failed_count,
    )

    return success_count, failed_count


def trigger_generations(
    notebook_id: str,
    episode_name: str | None = None,
    on_client: OpenNotebookClient | None = None,
) -> GenerationResult:
    """Trigger summary and podcast generation for a notebook.

    Args:
        notebook_id: ID of the notebook.
        episode_name: Optional name for the podcast episode.
        on_client: Optional Open Notebook client.

    Returns:
        GenerationResult with generation outcomes.
    """
    settings = get_settings()

    if on_client is None:
        on_client = OpenNotebookClient(
            base_url=settings.open_notebook_url,
            password=settings.open_notebook_password,
        )

    if episode_name is None:
        episode_name = f"Semaine du {datetime.now(timezone.utc).strftime('%d/%m/%Y')}"

    result = GenerationResult(notebook_id=notebook_id)

    # Generate podcast
    try:
        logger.info("podcast_generation_starting", notebook_id=notebook_id)

        job = on_client.generate_podcast(
            notebook_id=notebook_id,
            episode_name=episode_name,
            episode_profile=settings.podcast_episode_profile,
            speaker_profile=settings.podcast_speaker_profile,
        )

        job_id = job.get("job_id")
        if job_id:
            episode_id = on_client.wait_for_podcast(
                job_id=job_id,
                timeout=settings.podcast_generation_timeout,
            )

            if episode_id:
                result.episode_id = episode_id
                logger.info("podcast_generated", episode_id=episode_id)

                # Get audio URL
                episodes = on_client.list_episodes()
                for ep in episodes:
                    if ep.get("id") == episode_id:
                        result.audio_url = ep.get("audio_url")
                        break
            else:
                logger.warning("podcast_generation_timeout", job_id=job_id)

    except Exception as e:
        logger.error("podcast_generation_failed", error=str(e))
        result.success = False
        result.error = str(e)

    # Try to get summary from notebook notes
    try:
        notes = on_client.get_notebook_notes(notebook_id)
        for note in notes:
            if note.get("note_type") == "ai" or "summary" in note.get("title", "").lower():
                result.summary = note.get("content")
                break
    except Exception as e:
        logger.warning("summary_retrieval_failed", error=str(e))

    return result


def run_weekly_sync() -> SyncResult:
    """Run the full weekly sync process.

    This is the main entry point for the scheduler.

    Returns:
        SyncResult with sync outcomes.
    """
    logger.info("weekly_sync_started")
    settings = get_settings()

    # Create sync log
    sync_log = create_sync_log()
    sync_log_id = sync_log.id

    try:
        # Create clients
        readeck_client = ReadeckClient(
            base_url=settings.readeck_url,
            token=settings.readeck_token,
        )
        on_client = OpenNotebookClient(
            base_url=settings.open_notebook_url,
            password=settings.open_notebook_password,
        )

        # Get week's bookmarks
        bookmarks = get_week_bookmarks(readeck_client)

        if not bookmarks:
            logger.info("no_bookmarks_to_sync")
            update_sync_log(sync_log_id, status="completed", bookmarks_count=0)
            return SyncResult(
                notebook_id=None,
                bookmarks_count=0,
                sources_added=0,
                sources_failed=0,
                success=True,
            )

        # Update sync log with bookmark count
        update_sync_log(sync_log_id, status="running", bookmarks_count=len(bookmarks))

        # Create notebook
        notebook_id = create_weekly_notebook(bookmarks, on_client)
        update_sync_log(sync_log_id, status="running", notebook_id=notebook_id)

        # Add sources
        source_ids, add_failures = add_sources_to_notebook(notebook_id, bookmarks, on_client)

        # Wait for sources to process
        if source_ids:
            wait_for_sources(source_ids, on_client)

        # Trigger generations
        gen_result = trigger_generations(notebook_id, on_client=on_client)

        # Save episode if generated
        if gen_result.episode_id:
            add_episode(
                notebook_id=notebook_id,
                episode_id=gen_result.episode_id,
                episode_name=f"Semaine du {datetime.now(timezone.utc).strftime('%d/%m/%Y')}",
                audio_url=gen_result.audio_url,
            )

        # Update sync log
        update_sync_log(sync_log_id, status="completed")

        result = SyncResult(
            notebook_id=notebook_id,
            bookmarks_count=len(bookmarks),
            sources_added=len(source_ids),
            sources_failed=add_failures,
            episode_id=gen_result.episode_id,
            success=True,
        )

        logger.info(
            "weekly_sync_completed",
            notebook_id=notebook_id,
            bookmarks=len(bookmarks),
            sources=len(source_ids),
            episode_id=gen_result.episode_id,
        )

        return result

    except Exception as e:
        logger.error("weekly_sync_failed", error=str(e))
        update_sync_log(sync_log_id, status="failed", error=str(e))

        return SyncResult(
            notebook_id=None,
            bookmarks_count=0,
            sources_added=0,
            sources_failed=0,
            success=False,
            error=str(e),
        )
