"""Track resolution and stream URL handling.

DLNA media items carry direct, non-expiring HTTP URLs in their `res`
element, so get_stream_details is a pure cache lookup - no server round
trip, no signed-URL TTL like streaming services.

Track metadata is cached at browse time keyed by `{server_key}|{object_id}`.
On a cache miss (queue restored from the MA database after a restart) the
parent container is re-browsed once to repopulate the entry.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from music_assistant_models.enums import (
    ContentType,
    MediaType,
    StreamType,
)
from music_assistant_models.errors import MediaNotFoundError
from music_assistant_models.media_items import AudioFormat, Track
from music_assistant_models.streamdetails import StreamDetails

from .base import ProviderContract


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
        """Re-browse the parent container of a cache-missed track id."""
        server_key, _, object_id = item_id.partition("|")
        if not server_key or not object_id:
            return
        # without the parent id (cold cache) we cannot know where to re-browse
        parent_id = self._track_parent_hints.get(item_id)
        if not parent_id:
            return
        from .catalog import CatalogBrowseMixin  # noqa: PLC0415

        await CatalogBrowseMixin._browse_server(self, [server_key, parent_id])
