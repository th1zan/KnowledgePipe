"""Open Notebook API client."""

from __future__ import annotations

import time
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


class OpenNotebookError(Exception):
    """Base exception for Open Notebook client errors."""

    pass


class OpenNotebookClient:
    """Client for interacting with Open Notebook API.

    See AGENTS.md for full API documentation.
    """

    def __init__(
        self,
        base_url: str | None = None,
        password: str | None = None,
        timeout: int | None = None,
    ):
        """Initialize the Open Notebook client.

        Args:
            base_url: Open Notebook server URL. Defaults to settings.
            password: API password. Defaults to settings.
            timeout: Request timeout in seconds. Defaults to settings.
        """
        self.base_url = (base_url or settings.open_notebook_url).rstrip("/")
        self.password = password or settings.open_notebook_password
        self.timeout = timeout or settings.http_timeout
        self.headers = {"Authorization": f"Bearer {self.password}"}

    def _request(
        self,
        method: str,
        endpoint: str,
        **kwargs: Any,
    ) -> requests.Response:
        """Make an HTTP request to Open Notebook API.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE).
            endpoint: API endpoint path.
            **kwargs: Additional arguments passed to requests.

        Returns:
            Response object.

        Raises:
            OpenNotebookError: If the request fails.
        """
        url = f"{self.base_url}{endpoint}"
        kwargs.setdefault("headers", {}).update(self.headers)
        kwargs.setdefault("timeout", self.timeout)

        try:
            response = requests.request(method, url, **kwargs)
            return response
        except requests.RequestException as e:
            logger.error("opennotebook_request_failed", url=url, error=str(e))
            raise OpenNotebookError(f"Request to {url} failed: {e}") from e

    @retry(
        retry=retry_if_exception_type(OpenNotebookError),
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
                "opennotebook_server_error",
                status_code=response.status_code,
                endpoint=endpoint,
            )
            raise OpenNotebookError(f"Server error: {response.status_code}")

        return response

    def health_check(self) -> bool:
        """Check if Open Notebook is accessible.

        Returns:
            True if the connection is healthy, False otherwise.
        """
        try:
            response = self._request("GET", "/health")
            return response.status_code == 200
        except OpenNotebookError:
            return False

    # =========================================================================
    # Notebooks
    # =========================================================================

    def create_notebook(
        self,
        name: str,
        description: str = "",
    ) -> dict[str, Any]:
        """Create a new notebook.

        Args:
            name: Notebook name.
            description: Optional description.

        Returns:
            Created notebook dictionary.

        Raises:
            OpenNotebookError: If creation fails.
        """
        response = self._request_with_retry(
            "POST",
            "/api/notebooks",
            json={"name": name, "description": description},
        )

        if response.status_code in (200, 201):
            notebook = response.json()
            logger.info("notebook_created", notebook_id=notebook.get("id"), name=name)
            return notebook

        logger.error(
            "notebook_create_failed",
            status_code=response.status_code,
            response=response.text[:200],
        )
        raise OpenNotebookError(f"Failed to create notebook: {response.status_code}")

    def get_notebook(self, notebook_id: str) -> dict[str, Any] | None:
        """Get a notebook by ID.

        Args:
            notebook_id: Notebook ID.

        Returns:
            Notebook dictionary or None if not found.
        """
        try:
            response = self._request_with_retry("GET", f"/api/notebooks/{notebook_id}")

            if response.status_code == 200:
                return response.json()

            if response.status_code == 404:
                return None

            logger.warning(
                "notebook_fetch_failed",
                notebook_id=notebook_id,
                status_code=response.status_code,
            )
            return None

        except OpenNotebookError as e:
            logger.error("notebook_fetch_error", notebook_id=notebook_id, error=str(e))
            return None

    def list_notebooks(self) -> list[dict[str, Any]]:
        """List all notebooks.

        Returns:
            List of notebook dictionaries.
        """
        try:
            response = self._request_with_retry("GET", "/api/notebooks")

            if response.status_code == 200:
                return response.json()

            return []

        except OpenNotebookError as e:
            logger.error("notebooks_list_error", error=str(e))
            return []

    # =========================================================================
    # Sources
    # =========================================================================

    def add_source_url(
        self,
        notebook_id: str,
        url: str,
        embed: bool = True,
        async_processing: bool = True,
    ) -> dict[str, Any]:
        """Add a URL as a source to a notebook.

        Args:
            notebook_id: Target notebook ID.
            url: URL to add as source.
            embed: Enable vector embedding.
            async_processing: Process asynchronously.

        Returns:
            Source dictionary with ID and status.

        Raises:
            OpenNotebookError: If addition fails.
        """
        response = self._request_with_retry(
            "POST",
            "/api/sources",
            data={
                "type": "link",
                "notebooks": f'["{notebook_id}"]',
                "url": url,
                "embed": str(embed).lower(),
                "async_processing": str(async_processing).lower(),
            },
        )

        if response.status_code in (200, 201, 202):
            source = response.json()
            logger.info(
                "source_url_added",
                source_id=source.get("id"),
                url=url,
                notebook_id=notebook_id,
            )
            return source

        logger.error(
            "source_url_add_failed",
            url=url,
            status_code=response.status_code,
            response=response.text[:200],
        )
        raise OpenNotebookError(f"Failed to add URL source: {response.status_code}")

    def add_source_text(
        self,
        notebook_id: str,
        content: str,
        title: str,
        embed: bool = True,
    ) -> dict[str, Any]:
        """Add text content as a source to a notebook.

        Args:
            notebook_id: Target notebook ID.
            content: Text content.
            title: Source title.
            embed: Enable vector embedding.

        Returns:
            Source dictionary with ID and status.

        Raises:
            OpenNotebookError: If addition fails.
        """
        response = self._request_with_retry(
            "POST",
            "/api/sources",
            data={
                "type": "text",
                "notebooks": f'["{notebook_id}"]',
                "content": content,
                "title": title,
                "embed": str(embed).lower(),
            },
        )

        if response.status_code in (200, 201, 202):
            source = response.json()
            logger.info(
                "source_text_added",
                source_id=source.get("id"),
                title=title,
                notebook_id=notebook_id,
            )
            return source

        logger.error(
            "source_text_add_failed",
            title=title,
            status_code=response.status_code,
            response=response.text[:200],
        )
        raise OpenNotebookError(f"Failed to add text source: {response.status_code}")

    def get_source_status(self, source_id: str) -> dict[str, Any]:
        """Get the processing status of a source.

        Args:
            source_id: Source ID.

        Returns:
            Status dictionary with 'status' field.
        """
        try:
            response = self._request_with_retry(
                "GET",
                f"/api/sources/{source_id}/status",
            )

            if response.status_code == 200:
                return response.json()

            return {"status": "unknown"}

        except OpenNotebookError as e:
            logger.error("source_status_error", source_id=source_id, error=str(e))
            return {"status": "error"}

    def wait_for_source(
        self,
        source_id: str,
        timeout: int | None = None,
        poll_interval: int = 5,
    ) -> bool:
        """Wait for a source to finish processing.

        Args:
            source_id: Source ID.
            timeout: Maximum wait time in seconds. Defaults to settings.
            poll_interval: Time between status checks.

        Returns:
            True if processing completed successfully, False otherwise.
        """
        timeout = timeout or settings.source_processing_timeout
        start_time = time.time()

        while time.time() - start_time < timeout:
            status = self.get_source_status(source_id)
            current_status = status.get("status", "unknown")

            if current_status == "completed":
                logger.info("source_processing_completed", source_id=source_id)
                return True

            if current_status in ("failed", "error"):
                logger.error("source_processing_failed", source_id=source_id)
                return False

            logger.debug(
                "source_processing_waiting",
                source_id=source_id,
                status=current_status,
            )
            time.sleep(poll_interval)

        logger.warning("source_processing_timeout", source_id=source_id, timeout=timeout)
        return False

    def get_source(self, source_id: str) -> dict[str, Any] | None:
        """Get a source by ID.

        Args:
            source_id: Source ID.

        Returns:
            Source dictionary or None if not found.
        """
        try:
            response = self._request_with_retry("GET", f"/api/sources/{source_id}")

            if response.status_code == 200:
                return response.json()

            return None

        except OpenNotebookError as e:
            logger.error("source_fetch_error", source_id=source_id, error=str(e))
            return None

    # =========================================================================
    # Podcasts
    # =========================================================================

    def generate_podcast(
        self,
        notebook_id: str,
        episode_name: str,
        episode_profile: str | None = None,
        speaker_profile: str | None = None,
    ) -> dict[str, Any]:
        """Generate a podcast from a notebook.

        Args:
            notebook_id: Source notebook ID.
            episode_name: Name for the episode.
            episode_profile: Episode profile name. Defaults to settings.
            speaker_profile: Speaker profile name. Defaults to settings.

        Returns:
            Job dictionary with 'job_id' and 'status'.

        Raises:
            OpenNotebookError: If generation fails to start.
        """
        response = self._request_with_retry(
            "POST",
            "/api/podcasts/generate",
            json={
                "notebook_id": notebook_id,
                "episode_name": episode_name,
                "episode_profile": episode_profile or settings.podcast_episode_profile,
                "speaker_profile": speaker_profile or settings.podcast_speaker_profile,
            },
        )

        if response.status_code in (200, 201, 202):
            job = response.json()
            logger.info(
                "podcast_generation_started",
                job_id=job.get("job_id"),
                notebook_id=notebook_id,
                episode_name=episode_name,
            )
            return job

        logger.error(
            "podcast_generation_failed",
            notebook_id=notebook_id,
            status_code=response.status_code,
            response=response.text[:200],
        )
        raise OpenNotebookError(f"Failed to start podcast generation: {response.status_code}")

    def get_podcast_job_status(self, job_id: str) -> dict[str, Any]:
        """Get the status of a podcast generation job.

        Args:
            job_id: Job ID.

        Returns:
            Job status dictionary.
        """
        try:
            response = self._request_with_retry("GET", f"/api/podcasts/jobs/{job_id}")

            if response.status_code == 200:
                return response.json()

            return {"status": "unknown"}

        except OpenNotebookError as e:
            logger.error("podcast_job_status_error", job_id=job_id, error=str(e))
            return {"status": "error"}

    def wait_for_podcast(
        self,
        job_id: str,
        timeout: int | None = None,
        poll_interval: int = 10,
    ) -> str | None:
        """Wait for podcast generation to complete.

        Args:
            job_id: Job ID.
            timeout: Maximum wait time in seconds. Defaults to settings.
            poll_interval: Time between status checks.

        Returns:
            Episode ID if successful, None otherwise.
        """
        timeout = timeout or settings.podcast_generation_timeout
        start_time = time.time()

        while time.time() - start_time < timeout:
            status = self.get_podcast_job_status(job_id)
            current_status = status.get("status", "unknown")

            if current_status == "completed":
                episode_id = status.get("episode_id")
                logger.info(
                    "podcast_generation_completed",
                    job_id=job_id,
                    episode_id=episode_id,
                )
                return episode_id

            if current_status in ("failed", "error"):
                logger.error("podcast_generation_failed", job_id=job_id, status=status)
                return None

            logger.debug(
                "podcast_generation_waiting",
                job_id=job_id,
                status=current_status,
            )
            time.sleep(poll_interval)

        logger.warning("podcast_generation_timeout", job_id=job_id, timeout=timeout)
        return None

    def download_episode_audio(self, episode_id: str) -> bytes | None:
        """Download the audio file for an episode.

        Args:
            episode_id: Episode ID.

        Returns:
            Audio data as bytes, or None if not available.
        """
        try:
            response = self._request(
                "GET",
                f"/api/podcasts/episodes/{episode_id}/audio",
            )

            if response.status_code == 200:
                logger.info("episode_audio_downloaded", episode_id=episode_id)
                return response.content

            logger.warning(
                "episode_audio_download_failed",
                episode_id=episode_id,
                status_code=response.status_code,
            )
            return None

        except OpenNotebookError as e:
            logger.error(
                "episode_audio_download_error",
                episode_id=episode_id,
                error=str(e),
            )
            return None

    def list_episodes(self) -> list[dict[str, Any]]:
        """List all podcast episodes.

        Returns:
            List of episode dictionaries.
        """
        try:
            response = self._request_with_retry("GET", "/api/podcasts/episodes")

            if response.status_code == 200:
                return response.json()

            return []

        except OpenNotebookError as e:
            logger.error("episodes_list_error", error=str(e))
            return []

    def get_episode(self, episode_id: str) -> dict[str, Any] | None:
        """Get an episode by ID.

        Args:
            episode_id: Episode ID.

        Returns:
            Episode dictionary or None if not found.
        """
        try:
            response = self._request_with_retry(
                "GET",
                f"/api/podcasts/episodes/{episode_id}",
            )

            if response.status_code == 200:
                return response.json()

            return None

        except OpenNotebookError as e:
            logger.error("episode_fetch_error", episode_id=episode_id, error=str(e))
            return None

    # =========================================================================
    # Notes
    # =========================================================================

    def get_notebook_notes(self, notebook_id: str) -> list[dict[str, Any]]:
        """Get all notes for a notebook.

        Args:
            notebook_id: Notebook ID.

        Returns:
            List of note dictionaries.
        """
        try:
            response = self._request_with_retry(
                "GET",
                "/api/notes",
                params={"notebook_id": notebook_id},
            )

            if response.status_code == 200:
                return response.json()

            return []

        except OpenNotebookError as e:
            logger.error(
                "notebook_notes_fetch_error",
                notebook_id=notebook_id,
                error=str(e),
            )
            return []

    def create_note(
        self,
        notebook_id: str,
        title: str,
        content: str,
        note_type: str = "human",
    ) -> dict[str, Any]:
        """Create a note in a notebook.

        Args:
            notebook_id: Target notebook ID.
            title: Note title.
            content: Note content.
            note_type: Type of note ('human' or 'ai').

        Returns:
            Created note dictionary.

        Raises:
            OpenNotebookError: If creation fails.
        """
        response = self._request_with_retry(
            "POST",
            "/api/notes",
            json={
                "notebook_id": notebook_id,
                "title": title,
                "content": content,
                "note_type": note_type,
            },
        )

        if response.status_code in (200, 201):
            note = response.json()
            logger.info("note_created", note_id=note.get("id"), title=title)
            return note

        logger.error(
            "note_create_failed",
            status_code=response.status_code,
            response=response.text[:200],
        )
        raise OpenNotebookError(f"Failed to create note: {response.status_code}")

    # =========================================================================
    # Transformations
    # =========================================================================

    def apply_transformation(
        self,
        source_id: str,
        transformation_id: str,
    ) -> dict[str, Any]:
        """Apply a transformation to a source.

        Args:
            source_id: Source ID.
            transformation_id: Transformation ID.

        Returns:
            Result dictionary.

        Raises:
            OpenNotebookError: If transformation fails.
        """
        response = self._request_with_retry(
            "POST",
            f"/api/sources/{source_id}/insights",
            json={"transformation_id": transformation_id},
        )

        if response.status_code in (200, 201, 202):
            result = response.json()
            logger.info(
                "transformation_applied",
                source_id=source_id,
                transformation_id=transformation_id,
            )
            return result

        logger.error(
            "transformation_failed",
            source_id=source_id,
            transformation_id=transformation_id,
            status_code=response.status_code,
        )
        raise OpenNotebookError(f"Failed to apply transformation: {response.status_code}")

    def list_transformations(self) -> list[dict[str, Any]]:
        """List available transformations.

        Returns:
            List of transformation dictionaries.
        """
        try:
            response = self._request_with_retry("GET", "/api/transformations")

            if response.status_code == 200:
                return response.json()

            return []

        except OpenNotebookError as e:
            logger.error("transformations_list_error", error=str(e))
            return []
