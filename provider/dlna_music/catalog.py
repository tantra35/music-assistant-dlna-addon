"""Browse: root = one folder per discovered DLNA server; deeper levels =
ContentDirectory containers of that server.

Browse paths are hierarchical: `{instance_id}://{server_key}/{container_id}`
(the frontend derives breadcrumbs/parent from the "/"-separated segments).
DLNA container ids are absolute within the server's ContentDirectory, so only
the LAST path segment is ever browsed - intermediate segments are display
only. Container ids are percent-encoded when embedded in the path.
"""
from __future__ import annotations

import urllib.parse
from typing import TYPE_CHECKING

import didl_lite.didl_lite as didl_lite
from music_assistant_models.enums import ImageType
from music_assistant_models.errors import MediaNotFoundError
from music_assistant_models.media_items import BrowseFolder, MediaItemImage

from .base import ProviderContract
from .constants import ROOT_REFRESH_MIN_INTERVAL
from .media import parse_didl_duration

if TYPE_CHECKING:
    from collections.abc import Sequence

    from music_assistant_models.media_items import ItemMapping, MediaItemType


class CatalogBrowseMixin(ProviderContract):
    """browse() routing and ContentDirectory walking."""

    async def browse(
        self, path: str
    ) -> Sequence[MediaItemType | ItemMapping | BrowseFolder]:
        """Browse the provider tree."""
        subpath = path.split("://", 1)[1] if "://" in path else path
        parts = [urllib.parse.unquote(p) for p in subpath.split("/") if p.strip()]
        if not parts:
            return await self._browse_root()
        return await self._browse_server(parts)

    async def _browse_root(self) -> Sequence[BrowseFolder]:
        """Root: one folder per known DLNA server, sorted by name."""
        await self._registry.refresh_if_stale()
        items: list[BrowseFolder] = []
        for server in self._registry.servers:
            # the server's own device icon replaces the generic folder icon
            image = None
            if server.icon_url:
                image = MediaItemImage(
                    type=ImageType.THUMB,
                    path=server.icon_url,
                    provider=self.instance_id,
                    remotely_accessible=True,
                )
            items.append(
                BrowseFolder(
                    item_id=f"{server.key}|0",
                    name=server.name,
                    provider=self.instance_id,
                    path=f"{self.instance_id}://{server.key}",
                    image=image,
                )
            )
        return items

    async def _browse_server(
        self, parts: list[str]
    ) -> Sequence[MediaItemType | BrowseFolder]:
        """One level of a server's ContentDirectory."""
        server = self._registry.get(parts[0])
        if server is None:
            # cache cold (e.g. provider restart while the UI holds a path):
            # one immediate rescan, then fail if the server is really gone.
            await self._registry.refresh()
            server = self._registry.get(parts[0])
        if server is None:
            raise MediaNotFoundError(f"DLNA server not available: {parts[0]}")

        # parts[0] is the server key; a single segment means the server's
        # root container "0", deeper paths carry the container id last.
        container_id = parts[-1] if len(parts) > 1 else "0"
        result = await server.dms.async_browse_direct_children(container_id)
        # DmsDevice.BrowseResult.result is already a list of parsed
        # didl_lite objects (the profile parses the DIDL-Lite for us)
        objects = result.result or []

        folders: list[BrowseFolder] = []
        tracks: list[MediaItemType] = []
        for obj in objects:
            if isinstance(obj, didl_lite.Container):
                child_id = str(obj.id)
                folders.append(
                    BrowseFolder(
                        item_id=f"{server.key}|{child_id}",
                        name=obj.title,
                        provider=self.instance_id,
                        path=f"{self.instance_id}://{server.key}/"
                        + urllib.parse.quote(str(child_id), safe=""),
                    )
                )
            elif isinstance(obj, didl_lite.AudioItem):
                url = None
                mime = None
                size = None
                for res in obj.res or []:
                    if res.uri:
                        url = res.uri
                        if res.protocol_info:
                            mime = res.protocol_info.split(":")[2] or None
                        size = getattr(res, "size", None)
                        break
                if not url:
                    continue  # unplayable entry (e.g. radio stub without res)
                item_id = f"{server.key}|{obj.id}"
                self._track_cache[item_id] = {
                    "server_key": server.key,
                    "object_id": str(obj.id),
                    "parent_id": str(obj.parent_id),
                    "title": obj.title,
                    "duration": parse_didl_duration(res.duration),
                    "size": int(size) if size else None,
                    "url": url,
                    "mime": mime,
                }
                self._track_parent_hints[item_id] = str(obj.parent_id)
                tracks.append(self._build_track(item_id))

        folders.sort(key=lambda f: f.name.lower())
        tracks.sort(key=lambda t: t.name.lower())
        return [*folders, *tracks]
