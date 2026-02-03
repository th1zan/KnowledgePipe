"""RSS feed generation API endpoints.

This module provides endpoints for generating and serving RSS feeds
for podcasts and text reviews.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Response
from feedgen.feed import FeedGenerator

from src.config import get_settings
from src.database import get_latest_sync_logs, get_uploaded_episodes

logger = structlog.get_logger()

router = APIRouter(prefix="/feeds", tags=["feeds"])

# Feed cache
_feed_cache: dict[str, tuple[str, datetime]] = {}
CACHE_TTL_SECONDS = 300  # 5 minutes


def _get_cached_feed(name: str) -> str | None:
    """Get a cached feed if it exists and is not expired.

    Args:
        name: Name of the feed (e.g., 'podcast', 'reviews').

    Returns:
        Cached feed XML string or None if not cached or expired.
    """
    if name in _feed_cache:
        content, cached_at = _feed_cache[name]
        age = (datetime.now(timezone.utc) - cached_at).total_seconds()
        if age < CACHE_TTL_SECONDS:
            return content
    return None


def _set_cached_feed(name: str, content: str) -> None:
    """Cache a feed.

    Args:
        name: Name of the feed.
        content: Feed XML content.
    """
    _feed_cache[name] = (content, datetime.now(timezone.utc))


def invalidate_cache() -> None:
    """Invalidate all cached feeds."""
    global _feed_cache
    _feed_cache = {}
    logger.info("feed_cache_invalidated")


def _create_base_feed(
    title: str,
    description: str,
    link: str,
    feed_type: str = "rss",
) -> FeedGenerator:
    """Create a base feed generator with common settings.

    Args:
        title: Feed title.
        description: Feed description.
        link: Feed link.
        feed_type: Feed type ('rss' or 'atom').

    Returns:
        Configured FeedGenerator instance.
    """
    settings = get_settings()

    fg = FeedGenerator()
    fg.title(title)
    fg.description(description)
    fg.link(href=link, rel="alternate")
    fg.language("fr")
    fg.generator("Weekly Digest")
    fg.lastBuildDate(datetime.now(timezone.utc))

    return fg


def generate_podcast_feed() -> str:
    """Generate a podcast RSS feed (iTunes compatible).

    Returns:
        XML string of the podcast feed.
    """
    settings = get_settings()

    # Check cache
    cached = _get_cached_feed("podcast")
    if cached:
        return cached

    base_url = settings.audio_public_url.rstrip("/")

    fg = _create_base_feed(
        title="Weekly Digest Podcast",
        description="Synthèse hebdomadaire de vos lectures",
        link=base_url,
    )

    # iTunes-specific tags
    fg.load_extension("podcast")
    fg.podcast.itunes_category("Technology")
    fg.podcast.itunes_author("Weekly Digest")
    fg.podcast.itunes_explicit("no")
    fg.podcast.itunes_owner(name="Weekly Digest", email="podcast@example.com")
    fg.podcast.itunes_summary("Synthèse hebdomadaire de vos lectures sous forme de podcast")

    # Add episodes
    episodes = get_uploaded_episodes(limit=50)

    for episode in episodes:
        if not episode.public_url:
            continue

        fe = fg.add_entry()
        fe.id(episode.episode_id)
        fe.title(episode.episode_name or f"Episode {episode.id}")
        fe.description(f"Podcast généré le {episode.created_at.strftime('%d/%m/%Y')}")
        fe.published(episode.created_at.replace(tzinfo=timezone.utc))

        # Enclosure for audio
        fe.enclosure(
            url=episode.public_url,
            type="audio/mpeg",
            length=0,  # Length unknown, but required
        )

        # iTunes-specific entry tags
        fe.podcast.itunes_duration("00:00:00")  # Duration unknown
        fe.podcast.itunes_explicit("no")

    content = fg.rss_str(pretty=True).decode("utf-8")
    _set_cached_feed("podcast", content)

    logger.info("podcast_feed_generated", episode_count=len(episodes))
    return content


def generate_reviews_feed() -> str:
    """Generate a reviews RSS feed with text summaries.

    Returns:
        XML string of the reviews feed.
    """
    settings = get_settings()

    # Check cache
    cached = _get_cached_feed("reviews")
    if cached:
        return cached

    base_url = settings.audio_public_url.rstrip("/")

    fg = _create_base_feed(
        title="Weekly Digest Reviews",
        description="Synthèses hebdomadaires de vos lectures",
        link=base_url,
    )

    # Add sync logs as entries
    sync_logs = get_latest_sync_logs(limit=50)

    for log in sync_logs:
        if log.status != "completed" or not log.notebook_id:
            continue

        fe = fg.add_entry()
        fe.id(log.notebook_id)
        fe.title(f"Semaine du {log.started_at.strftime('%d/%m/%Y')}")
        fe.published(log.started_at.replace(tzinfo=timezone.utc))

        # Build description from log info
        description = f"Synthèse de {log.bookmarks_count} articles"
        if log.completed_at:
            description += f" (généré le {log.completed_at.strftime('%d/%m/%Y à %H:%M')})"

        fe.description(description)
        fe.link(href=f"{base_url}/notebooks/{log.notebook_id}", rel="alternate")

    content = fg.rss_str(pretty=True).decode("utf-8")
    _set_cached_feed("reviews", content)

    logger.info("reviews_feed_generated", entry_count=len(sync_logs))
    return content


@router.get("/podcast.rss")
async def get_podcast_feed() -> Response:
    """Get the podcast RSS feed.

    Returns:
        RSS feed XML response.
    """
    content = generate_podcast_feed()
    return Response(
        content=content,
        media_type="application/rss+xml; charset=utf-8",
    )


@router.get("/reviews.rss")
async def get_reviews_feed() -> Response:
    """Get the reviews RSS feed.

    Returns:
        RSS feed XML response.
    """
    content = generate_reviews_feed()
    return Response(
        content=content,
        media_type="application/rss+xml; charset=utf-8",
    )


@router.post("/regenerate")
async def regenerate_feeds() -> dict[str, Any]:
    """Regenerate all RSS feeds (invalidate cache).

    Returns:
        Status message.
    """
    invalidate_cache()

    # Pre-generate feeds
    generate_podcast_feed()
    generate_reviews_feed()

    return {"status": "ok", "message": "Feeds regenerated"}
