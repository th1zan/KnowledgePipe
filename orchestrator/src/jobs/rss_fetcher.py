"""RSS Fetcher job.

This module fetches RSS feeds, filters new entries, and adds them to Readeck.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import feedparser
import structlog

from src.clients import ReadeckClient
from src.config import get_settings
from src.database import add_rss_item, is_rss_item_processed

logger = structlog.get_logger()


@dataclass
class FeedEntry:
    """Represents a parsed RSS feed entry.

    Attributes:
        guid: Unique identifier (entry id or link).
        url: URL of the article.
        title: Title of the article.
        feed_url: URL of the source feed.
        feed_title: Title of the source feed.
    """

    guid: str
    url: str
    title: str | None
    feed_url: str
    feed_title: str | None


@dataclass
class ProcessingResult:
    """Result of processing RSS feeds.

    Attributes:
        total_entries: Total number of entries found.
        new_entries: Number of new entries (not previously processed).
        added_count: Number of entries successfully added to Readeck.
        failed_count: Number of entries that failed to add.
        errors: List of error messages.
    """

    total_entries: int
    new_entries: int
    added_count: int
    failed_count: int
    errors: list[str]


def parse_feed_entry(entry: Any, feed_url: str, feed_title: str | None) -> FeedEntry:
    """Parse a feedparser entry into a FeedEntry.

    Args:
        entry: A feedparser entry object.
        feed_url: URL of the source feed.
        feed_title: Title of the source feed.

    Returns:
        A FeedEntry instance.
    """
    # Use entry id if available, otherwise use link
    guid = entry.get("id") or entry.get("link") or ""
    url = entry.get("link") or ""
    title = entry.get("title")

    return FeedEntry(
        guid=guid,
        url=url,
        title=title,
        feed_url=feed_url,
        feed_title=feed_title,
    )


def fetch_feed(url: str, timeout: int = 30) -> list[FeedEntry]:
    """Fetch and parse an RSS feed.

    Args:
        url: URL of the RSS feed.
        timeout: Request timeout in seconds.

    Returns:
        List of FeedEntry instances.

    Raises:
        ValueError: If the feed URL is invalid or the feed cannot be parsed.
    """
    if not url or not url.startswith(("http://", "https://")):
        raise ValueError(f"Invalid feed URL: {url}")

    logger.debug("fetching_feed", url=url)

    # feedparser handles timeouts via request_headers
    feed = feedparser.parse(url, request_headers={"User-Agent": "WeeklyDigest/1.0"})

    # Check for errors
    if feed.bozo and feed.bozo_exception:
        # bozo means the feed had issues, but might still be partially parseable
        exception = feed.bozo_exception
        # Only raise for critical errors
        if isinstance(exception, (OSError, TimeoutError)):
            raise ValueError(f"Failed to fetch feed: {exception}")
        logger.warning("feed_parse_warning", url=url, error=str(exception))

    feed_title = feed.feed.get("title") if hasattr(feed, "feed") else None

    entries = []
    for entry in feed.entries:
        parsed = parse_feed_entry(entry, url, feed_title)
        if parsed.guid and parsed.url:  # Skip entries without required fields
            entries.append(parsed)
        else:
            logger.warning("skipping_entry_missing_fields", feed_url=url, entry=entry)

    logger.info("feed_fetched", url=url, entry_count=len(entries))
    return entries


def process_entry(
    entry: FeedEntry,
    readeck_client: ReadeckClient,
    labels: list[str] | None = None,
) -> bool:
    """Process a single RSS entry.

    Checks if the entry has already been processed, and if not,
    adds it to Readeck and records it in the database.

    Args:
        entry: The FeedEntry to process.
        readeck_client: Readeck API client.
        labels: Optional labels to apply to the bookmark.

    Returns:
        True if the entry was successfully added, False otherwise.
    """
    # Check if already processed
    if is_rss_item_processed(entry.guid):
        logger.debug("entry_already_processed", guid=entry.guid)
        return False

    # Build labels
    entry_labels = list(labels) if labels else []
    entry_labels.append("rss")
    if entry.feed_title:
        entry_labels.append(entry.feed_title)

    # Add to Readeck
    try:
        bookmark_id = readeck_client.add_bookmark(
            url=entry.url,
            title=entry.title,
            labels=entry_labels,
        )

        if bookmark_id:
            # Record in database
            add_rss_item(
                guid=entry.guid,
                url=entry.url,
                title=entry.title,
                feed_url=entry.feed_url,
                bookmark_id=bookmark_id,
            )
            logger.info(
                "entry_added",
                guid=entry.guid,
                title=entry.title,
                bookmark_id=bookmark_id,
            )
            return True
        else:
            logger.warning("bookmark_creation_failed", guid=entry.guid, url=entry.url)
            return False

    except Exception as e:
        logger.error("entry_processing_error", guid=entry.guid, error=str(e))
        return False


def process_all_feeds(
    feed_urls: list[str] | None = None,
    readeck_client: ReadeckClient | None = None,
) -> ProcessingResult:
    """Process all configured RSS feeds.

    Args:
        feed_urls: Optional list of feed URLs. If not provided, uses config.
        readeck_client: Optional Readeck client. If not provided, creates one.

    Returns:
        ProcessingResult with statistics about the processing.
    """
    settings = get_settings()

    # Get feed URLs from config if not provided
    if feed_urls is None:
        feed_urls = settings.rss_feed_list

    if not feed_urls:
        logger.warning("no_feeds_configured")
        return ProcessingResult(
            total_entries=0,
            new_entries=0,
            added_count=0,
            failed_count=0,
            errors=["No feeds configured"],
        )

    # Create Readeck client if not provided
    if readeck_client is None:
        readeck_client = ReadeckClient(
            base_url=settings.readeck_url,
            token=settings.readeck_token,
        )

    total_entries = 0
    new_entries = 0
    added_count = 0
    failed_count = 0
    errors: list[str] = []

    logger.info("processing_feeds_started", feed_count=len(feed_urls))

    for feed_url in feed_urls:
        try:
            entries = fetch_feed(feed_url)
            total_entries += len(entries)

            for entry in entries:
                # Check if new
                if not is_rss_item_processed(entry.guid):
                    new_entries += 1
                    if process_entry(entry, readeck_client):
                        added_count += 1
                    else:
                        failed_count += 1

        except ValueError as e:
            error_msg = f"Failed to fetch {feed_url}: {e}"
            logger.error("feed_fetch_failed", url=feed_url, error=str(e))
            errors.append(error_msg)

        except Exception as e:
            error_msg = f"Unexpected error processing {feed_url}: {e}"
            logger.error("feed_processing_error", url=feed_url, error=str(e))
            errors.append(error_msg)

    result = ProcessingResult(
        total_entries=total_entries,
        new_entries=new_entries,
        added_count=added_count,
        failed_count=failed_count,
        errors=errors,
    )

    logger.info(
        "processing_feeds_completed",
        total=total_entries,
        new=new_entries,
        added=added_count,
        failed=failed_count,
        errors=len(errors),
    )

    return result


def run_rss_job() -> ProcessingResult:
    """Run the RSS fetcher job.

    This is the main entry point for the scheduler.

    Returns:
        ProcessingResult with statistics about the processing.
    """
    logger.info("rss_job_started")

    try:
        result = process_all_feeds()
        logger.info(
            "rss_job_completed",
            added=result.added_count,
            failed=result.failed_count,
        )
        return result

    except Exception as e:
        logger.error("rss_job_failed", error=str(e))
        return ProcessingResult(
            total_entries=0,
            new_entries=0,
            added_count=0,
            failed_count=0,
            errors=[f"Job failed: {e}"],
        )
