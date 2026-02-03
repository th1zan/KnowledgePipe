"""Readeck API client."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import requests
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.config import settings

logger = structlog.get_logger()


class ReadeckError(Exception):
    """Base exception for Readeck client errors."""

    pass


class ReadeckClient:
    """Client for interacting with Readeck API.

    See AGENTS.md for full API documentation.
    """

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        timeout: int | None = None,
    ):
        """Initialize the Readeck client.

        Args:
            base_url: Readeck server URL. Defaults to settings.
            token: API token. Defaults to settings.
            timeout: Request timeout in seconds. Defaults to settings.
        """
        self.base_url = (base_url or settings.readeck_url).rstrip("/")
        self.token = token or settings.readeck_token
        self.timeout = timeout or settings.http_timeout
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def _request(
        self,
        method: str,
        endpoint: str,
        **kwargs: Any,
    ) -> requests.Response:
        """Make an HTTP request to Readeck API.

        Args:
            method: HTTP method (GET, POST, PATCH, DELETE).
            endpoint: API endpoint path.
            **kwargs: Additional arguments passed to requests.

        Returns:
            Response object.

        Raises:
            ReadeckError: If the request fails.
        """
        url = f"{self.base_url}{endpoint}"
        kwargs.setdefault("headers", {}).update(self.headers)
        kwargs.setdefault("timeout", self.timeout)

        try:
            response = requests.request(method, url, **kwargs)
            return response
        except requests.RequestException as e:
            logger.error("readeck_request_failed", url=url, error=str(e))
            raise ReadeckError(f"Request to {url} failed: {e}") from e

    @retry(
        retry=retry_if_exception_type(ReadeckError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _request_with_retry(
        self,
        method: str,
        endpoint: str,
        **kwargs: Any,
    ) -> requests.Response:
        """Make an HTTP request with retry logic.

        Retries on 5xx errors and connection errors.
        """
        response = self._request(method, endpoint, **kwargs)

        # Retry on server errors
        if response.status_code >= 500:
            logger.warning(
                "readeck_server_error",
                status_code=response.status_code,
                endpoint=endpoint,
            )
            raise ReadeckError(f"Server error: {response.status_code}")

        return response

    def health_check(self) -> bool:
        """Check if Readeck is accessible and authenticated.

        Returns:
            True if the connection is healthy, False otherwise.
        """
        try:
            response = self._request("GET", "/api/profile")
            return response.status_code == 200
        except ReadeckError:
            return False

    def add_bookmark(
        self,
        url: str,
        title: str | None = None,
        labels: list[str] | None = None,
    ) -> str | None:
        """Add a new bookmark to Readeck.

        Args:
            url: URL to bookmark.
            title: Optional title override.
            labels: Optional list of labels.

        Returns:
            Bookmark ID if successful, None otherwise.
        """
        data: dict[str, Any] = {"url": url}
        if title:
            data["title"] = title
        if labels:
            data["labels"] = labels

        try:
            response = self._request_with_retry("POST", "/api/bookmarks", json=data)

            if response.status_code in (200, 201, 202):
                bookmark_id = response.headers.get("Bookmark-Id")
                logger.info("bookmark_added", url=url, bookmark_id=bookmark_id)
                return bookmark_id

            logger.warning(
                "bookmark_add_failed",
                url=url,
                status_code=response.status_code,
                response=response.text[:200],
            )
            return None

        except ReadeckError as e:
            logger.error("bookmark_add_error", url=url, error=str(e))
            return None

    def get_bookmarks(
        self,
        range_start: str | None = None,
        range_end: str | None = None,
        labels: list[str] | None = None,
        is_marked: bool | None = None,
        is_archived: bool | None = None,
        read_status: list[str] | None = None,
        sort: str = "-created",
        limit: int = 100,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        """Get bookmarks with optional filters.

        Args:
            range_start: Start date (ISO format).
            range_end: End date (ISO format).
            labels: Filter by labels.
            is_marked: Filter by marked status.
            is_archived: Filter by archived status.
            read_status: Filter by read status (unread, reading, read).
            sort: Sort order (e.g., '-created' for desc by creation date).
            limit: Number of results per page.
            page: Page number.

        Returns:
            List of bookmark dictionaries.
        """
        params: dict[str, Any] = {
            "sort": sort,
            "limit": limit,
            "page": page,
        }

        if range_start:
            params["range_start"] = range_start
        if range_end:
            params["range_end"] = range_end
        if labels:
            params["labels"] = ",".join(labels)
        if is_marked is not None:
            params["is_marked"] = str(is_marked).lower()
        if is_archived is not None:
            params["is_archived"] = str(is_archived).lower()
        if read_status:
            params["read_status"] = ",".join(read_status)

        try:
            response = self._request_with_retry("GET", "/api/bookmarks", params=params)

            if response.status_code == 200:
                return response.json()

            logger.warning(
                "bookmarks_fetch_failed",
                status_code=response.status_code,
            )
            return []

        except ReadeckError as e:
            logger.error("bookmarks_fetch_error", error=str(e))
            return []

    def get_week_bookmarks(self) -> list[dict[str, Any]]:
        """Get bookmarks from the last 7 days.

        Returns:
            List of bookmark dictionaries.
        """
        since = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        return self.get_bookmarks(range_start=since, sort="-created")

    def get_bookmark(self, bookmark_id: str) -> dict[str, Any] | None:
        """Get details of a specific bookmark.

        Args:
            bookmark_id: Bookmark ID.

        Returns:
            Bookmark dictionary or None if not found.
        """
        try:
            response = self._request_with_retry("GET", f"/api/bookmarks/{bookmark_id}")

            if response.status_code == 200:
                return response.json()

            if response.status_code == 404:
                logger.info("bookmark_not_found", bookmark_id=bookmark_id)
                return None

            logger.warning(
                "bookmark_fetch_failed",
                bookmark_id=bookmark_id,
                status_code=response.status_code,
            )
            return None

        except ReadeckError as e:
            logger.error("bookmark_fetch_error", bookmark_id=bookmark_id, error=str(e))
            return None

    def get_bookmark_content(
        self,
        bookmark_id: str,
        format: str = "md",
    ) -> str | None:
        """Get the extracted content of a bookmark.

        Args:
            bookmark_id: Bookmark ID.
            format: Content format ('md' for Markdown, 'html' for HTML).

        Returns:
            Extracted content as string, or None if not available.
        """
        endpoint = f"/api/bookmarks/{bookmark_id}/article"
        if format == "md":
            endpoint += ".md"

        try:
            response = self._request_with_retry("GET", endpoint)

            if response.status_code == 200:
                return response.text

            if response.status_code == 404:
                logger.info(
                    "bookmark_content_not_found",
                    bookmark_id=bookmark_id,
                )
                return None

            logger.warning(
                "bookmark_content_fetch_failed",
                bookmark_id=bookmark_id,
                status_code=response.status_code,
            )
            return None

        except ReadeckError as e:
            logger.error(
                "bookmark_content_fetch_error",
                bookmark_id=bookmark_id,
                error=str(e),
            )
            return None

    def update_bookmark(
        self,
        bookmark_id: str,
        is_marked: bool | None = None,
        is_archived: bool | None = None,
        labels: list[str] | None = None,
        add_labels: list[str] | None = None,
        remove_labels: list[str] | None = None,
    ) -> bool:
        """Update a bookmark's properties.

        Args:
            bookmark_id: Bookmark ID.
            is_marked: Set marked status.
            is_archived: Set archived status.
            labels: Replace all labels.
            add_labels: Add labels to existing.
            remove_labels: Remove labels from existing.

        Returns:
            True if update was successful.
        """
        data: dict[str, Any] = {}

        if is_marked is not None:
            data["is_marked"] = is_marked
        if is_archived is not None:
            data["is_archived"] = is_archived
        if labels is not None:
            data["labels"] = labels
        if add_labels:
            data["add_labels"] = add_labels
        if remove_labels:
            data["remove_labels"] = remove_labels

        if not data:
            return True  # Nothing to update

        try:
            response = self._request_with_retry(
                "PATCH",
                f"/api/bookmarks/{bookmark_id}",
                json=data,
            )

            if response.status_code in (200, 204):
                logger.info("bookmark_updated", bookmark_id=bookmark_id)
                return True

            logger.warning(
                "bookmark_update_failed",
                bookmark_id=bookmark_id,
                status_code=response.status_code,
            )
            return False

        except ReadeckError as e:
            logger.error(
                "bookmark_update_error",
                bookmark_id=bookmark_id,
                error=str(e),
            )
            return False

    def delete_bookmark(self, bookmark_id: str) -> bool:
        """Delete a bookmark.

        Args:
            bookmark_id: Bookmark ID.

        Returns:
            True if deletion was successful.
        """
        try:
            response = self._request_with_retry(
                "DELETE",
                f"/api/bookmarks/{bookmark_id}",
            )

            if response.status_code in (200, 204, 404):
                logger.info("bookmark_deleted", bookmark_id=bookmark_id)
                return True

            logger.warning(
                "bookmark_delete_failed",
                bookmark_id=bookmark_id,
                status_code=response.status_code,
            )
            return False

        except ReadeckError as e:
            logger.error(
                "bookmark_delete_error",
                bookmark_id=bookmark_id,
                error=str(e),
            )
            return False

    def get_labels(self) -> list[dict[str, Any]]:
        """Get all labels with their counts.

        Returns:
            List of label dictionaries with 'name' and 'count'.
        """
        try:
            response = self._request_with_retry("GET", "/api/bookmarks/labels")

            if response.status_code == 200:
                return response.json()

            return []

        except ReadeckError as e:
            logger.error("labels_fetch_error", error=str(e))
            return []
