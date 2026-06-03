"""AL\\CE — HTTP client for the Continuum knowledge-base server.

Thin async wrapper over Continuum's REST API used by
:class:`~backend.services.knowledge.continuum_backend.ContinuumBackend`.
It owns three concerns and nothing else:

* transport — issue authenticated requests against ``{base_url}/api`` and
  raise :class:`ContinuumError` on non-2xx responses;
* folder resolution — translate Alice's slash-delimited ``folder_path``
  (e.g. ``"work/projects"``) to a Continuum folder UUID and back, caching
  the folder forest for a short TTL to avoid per-call round-trips;
* nothing else — no business logic, no document shaping (that lives in the
  backend), so this module stays small and independently testable.

A fresh :class:`httpx.AsyncClient` is created per request (mirroring the
pattern already used in ``api/routes/config.py`` and the managed-service
clients) so the client carries no lifecycle obligations for callers.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from loguru import logger


class ContinuumError(RuntimeError):
    """Raised when the Continuum server returns an error or is unreachable."""


class ContinuumClient:
    """Async REST client for a single Continuum server instance.

    Args:
        base_url: Server root (without ``/api``), e.g. ``http://localhost:3001``.
        api_token: Optional bearer token; sent as ``Authorization`` when set.
        timeout_s: Per-request timeout in seconds.
        folder_cache_ttl_s: Lifetime of the cached folder forest.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_token: str | None,
        timeout_s: float,
        folder_cache_ttl_s: float,
    ) -> None:
        self._api_base = base_url.rstrip("/") + "/api"
        self._token = api_token
        self._timeout = timeout_s
        self._folder_ttl = folder_cache_ttl_s
        self._log = logger.bind(component="ContinuumClient")
        # Cached folder maps: path→id and id→path, with the fetch timestamp.
        self._folder_cache_at: float = 0.0
        self._path_to_id: dict[str, str] = {}
        self._id_to_path: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        if self._token:
            return {"Authorization": f"Bearer {self._token}"}
        return {}

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: Any | None = None,
    ) -> Any:
        """Issue a request and return the decoded JSON body.

        This is the single low-level transport used by both the typed
        helpers below and external callers (e.g. the ``continuum`` plugin)
        that need endpoints without a dedicated helper.

        Raises:
            ContinuumError: on transport failure or a non-2xx response.
        """
        url = f"{self._api_base}{path}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.request(
                    method, url, json=json, headers=self._headers(),
                )
        except httpx.HTTPError as exc:
            raise ContinuumError(f"Continuum unreachable: {exc}") from exc

        if response.status_code >= 400:
            raise ContinuumError(
                f"Continuum {method} {path} → {response.status_code}: "
                f"{response.text[:200]}"
            )
        if not response.content:
            return None
        return response.json()

    # ------------------------------------------------------------------
    # Notes
    # ------------------------------------------------------------------

    async def list_notes(self) -> list[dict[str, Any]]:
        """Return every note (ordered by ``updatedAt`` server-side)."""
        return await self.request("GET", "/notes") or []

    async def get_note(self, note_id: str) -> dict[str, Any] | None:
        """Return a single note, or ``None`` if it does not exist."""
        try:
            return await self.request("GET", f"/notes/{note_id}")
        except ContinuumError as exc:
            if "404" in str(exc):
                return None
            raise

    async def create_note(self, body: dict[str, Any]) -> dict[str, Any]:
        """Create a note and return the materialised row."""
        return await self.request("POST", "/notes", json=body)

    async def update_note(
        self, note_id: str, body: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Apply a partial update; ``None`` if the note is missing."""
        try:
            return await self.request("PUT", f"/notes/{note_id}", json=body)
        except ContinuumError as exc:
            if "404" in str(exc):
                return None
            raise

    async def delete_note(self, note_id: str) -> bool:
        """Delete a note. Returns ``True`` when the server confirms removal."""
        try:
            await self.request("DELETE", f"/notes/{note_id}")
        except ContinuumError as exc:
            if "404" in str(exc):
                return False
            raise
        return True

    async def search_notes(
        self,
        query: str,
        *,
        limit: int,
        folder_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Semantic search; returns ``AiSearchHit`` dicts (id/title/snippet/score)."""
        body: dict[str, Any] = {"query": query, "limit": limit}
        if folder_id is not None:
            body["folderId"] = folder_id
        return await self.request("POST", "/notes/search", json=body) or []

    # ------------------------------------------------------------------
    # Folder path resolution
    # ------------------------------------------------------------------

    async def _ensure_folders(self) -> None:
        """Refresh the folder path↔id cache when stale."""
        if (time.monotonic() - self._folder_cache_at) < self._folder_ttl:
            return
        forest = await self.request("GET", "/folders") or []
        path_to_id: dict[str, str] = {}
        id_to_path: dict[str, str] = {}

        def walk(nodes: list[dict[str, Any]], prefix: str) -> None:
            for node in nodes:
                path = f"{prefix}/{node['slug']}" if prefix else node["slug"]
                path_to_id[path] = node["id"]
                id_to_path[node["id"]] = path
                walk(node.get("children") or [], path)

        walk(forest, "")
        self._path_to_id = path_to_id
        self._id_to_path = id_to_path
        self._folder_cache_at = time.monotonic()

    async def resolve_folder_id(self, folder_path: str | None) -> str | None:
        """Map a slash-delimited folder path to a folder UUID.

        Returns ``None`` for an empty path (root) or when the path does not
        match any folder — callers treat both as "place at root".
        """
        if not folder_path:
            return None
        await self._ensure_folders()
        folder_id = self._path_to_id.get(folder_path.strip("/"))
        if folder_id is None:
            self._log.debug("folder_path {!r} not found; using root", folder_path)
        return folder_id

    async def resolve_folder_path(self, folder_id: str | None) -> str:
        """Map a folder UUID back to its slash-delimited path (``""`` = root)."""
        if not folder_id:
            return ""
        await self._ensure_folders()
        return self._id_to_path.get(folder_id, "")

    def invalidate_folder_cache(self) -> None:
        """Drop the cached folder forest so the next resolve refetches.

        Call after any operation that mutates the folder tree (e.g.
        creating a folder) so subsequent path↔id resolution reflects the
        change immediately instead of waiting out the TTL. Kept cheap and
        synchronous: it only resets the cache markers, never performs I/O.
        """
        self._folder_cache_at = 0.0
        self._path_to_id = {}
        self._id_to_path = {}
