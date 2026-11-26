"""Track resolution and stream URL handling.

DLNA media items carry direct, non-expiring HTTP URLs in their `res`
element, so get_stream_details is a pure cache lookup - no server round
trip, no signed-URL TTL like streaming services.

Track metadata is cached at browse time keyed by `{server_key}|{object_id}`.
On a cache miss (queue restored from the MA database after a restart) the
entry is first looked up in the persistent MA cache (written at browse
time), then - as a fallback - the parent container is re-browsed once.
"""
from __future__ import annotations

import urllib.parse

from music_assistant_models.enums import (
    ContentType,
    MediaType,
    StreamType,
)
from music_assistant_models.errors import MediaNotFoundError
from music_assistant_models.media_items import AudioFormat, Track
from music_assistant_models.streamdetails import StreamDetails

from .base import ProviderContract
from .constants import CACHE_KEY_PREFIX


def parse_didl_duration(raw: str | None) -> int:
    """Parse a UPnP duration (H:MM:SS[.frac]) into seconds."""
    if not raw:
        return 0
    total = 0
    for chunk in raw.split(".")[0].split(":"):
        total = total * 60 + int(chunk or 0)
    return max(0, total)


class MediaApiMixin(ProviderContract):
    """get_track / get_stream_details on top of the browse cache."""

    def _build_track(self, item_id: str) -> Track:
        """Build a Track model from a cached browse entry."""
        from music_assistant_models.media_items import ProviderMapping  # noqa: PLC0415

        info = self._track_cache[item_id]
        return Track(
            item_id=item_id,
            provider=self.instance_id,
            name=info["title"],
            duration=info["duration"],
            provider_mappings={
                ProviderMapping(
                    item_id=item_id,
                    provider_domain=self.domain,
                    provider_instance=self.instance_id,
                )
            },
        )

    async def get_track(self, prov_track_id: str) -> Track:
        """Return track metadata for a queue item, re-browsing on cache miss."""
        if prov_track_id not in self._track_cache:
            await self._recover_track(prov_track_id)
        if prov_track_id not in self._track_cache:
            raise MediaNotFoundError(f"Track not found on any DLNA server: {prov_track_id}")
        return self._build_track(prov_track_id)

    async def get_stream_details(
        self, item_id: str, media_type: MediaType
    ) -> StreamDetails:
        """Return the direct HTTP URL of a browsed DLNA item."""
        if item_id not in self._track_cache:
            await self._recover_track(item_id)
        info = self._track_cache.get(item_id)
        if info is None:
            raise MediaNotFoundError(f"Track not found on any DLNA server: {item_id}")
        content_type = ContentType.try_parse(info["mime"] or "") or ContentType.MP3
        return StreamDetails(
            provider=self.instance_id,
            item_id=item_id,
            media_type=MediaType.TRACK,
            audio_format=AudioFormat(content_type=content_type),
            stream_type=StreamType.HTTP,
            path=info["url"],
            duration=info["duration"],
            size=info["size"],
            can_seek=True,
            allow_seek=True,
        )

    async def _recover_track(self, item_id: str) -> None:
        """Restore a cache-missed track id (cold cache, e.g. after restart).

        Order: persistent MA cache (no network), then a re-browse of the
        parent container - parent id either hinted by a live browse or
        derived from a path-style object id (e.g. miniDLNA).
        """
        server_key, _, object_id = item_id.partition("|")
        if not server_key or not object_id:
            return
        if await self._load_persisted(item_id):
            return
        parent_id = (
            self._track_parent_hints.get(item_id) or self._derive_parent_id(object_id)
        )
        if not parent_id:
            return
        await self._browse_server([server_key, parent_id])

    async def _load_persisted(self, item_id: str) -> bool:
        """Load one track entry from the persistent MA cache into the hot cache."""
        try:
            data = await self.mass.cache.get(
                CACHE_KEY_PREFIX + item_id, provider=self.instance_id
            )
        except Exception as err:  # noqa: BLE001 - a broken cache must not break playback
            self.logger.debug("DLNA: cache read failed for %s: %s", item_id, err)
            return False
        if not isinstance(data, dict) or not data.get("url"):
            return False
        self._track_cache[item_id] = data
        self._track_parent_hints[item_id] = str(data.get("parent_id") or "")
        return True

    @staticmethod
    def _derive_parent_id(object_id: str) -> str | None:
        """Parent container id of a derivable object id, else None.

        Two common ContentDirectory id conventions allow deriving the
        parent without a hint: file paths (miniDLNA: dirname; server root
        container is "0") and ``$``-separated hierarchies (miniDLNA and
        others: ``64$12`` -> parent ``64``). Opaque ids (bare uuids) yield
        no parent and cannot be recovered without a hint or the persistent
        cache.
        """
        decoded = urllib.parse.unquote(object_id)
        for candidate in (decoded, object_id):
            if "/" in candidate:
                parent = candidate.rstrip("/").rsplit("/", 1)[0]
                return parent or "0"
        for candidate in (decoded, object_id):
            if "$" in candidate:
                parent = candidate.rsplit("$", 1)[0]
                return parent or "0"
        return None
