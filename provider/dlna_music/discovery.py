"""DLNA media server discovery: manual description URLs + periodic SSDP scan.

The registry keeps one DmsDevice (async_upnp_client profile wrapper around a
UPnP ContentDirectory server) per server, keyed by a path-safe, STABLE key
derived from the device UDN - the same key is used in browse paths, so the
UI navigation survives provider restarts.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from urllib.parse import urljoin

from async_upnp_client.aiohttp import AiohttpRequester
from async_upnp_client.client_factory import UpnpFactory
from async_upnp_client.profiles.dlna import DmsDevice

from .constants import ROOT_REFRESH_MIN_INTERVAL


def server_key_from_udn(udn: str | None) -> str:
    """Return a stable, path-safe key for a server: the uuid of its UDN.

    UDNs look like "uuid:1c2ab410-..."; the uuid part contains only hex
    digits and dashes, safe to use as a browse path segment.
    """
    key = (udn or "").removeprefix("uuid:").strip()
    return key or "unknown"


@dataclass
class DlnaServer:
    """One discovered DLNA media server."""

    key: str
    udn: str
    name: str
    location: str
    dms: DmsDevice
    icon_url: str | None = None


class ServerRegistry:
    """Cache of DLNA media servers, refreshed from SSDP and manual URLs."""

    def __init__(self, manual_urls: list[str], logger) -> None:
        """Initialize the registry; servers are found on refresh()."""
        self._manual_urls = [u.strip() for u in manual_urls or [] if u.strip()]
        self.logger = logger
        self._servers: dict[str, DlnaServer] = {}
        self._factory = UpnpFactory(AiohttpRequester())
        self._lock = asyncio.Lock()
        self._last_refresh: float = 0.0

    @property
    def servers(self) -> list[DlnaServer]:
        """Return all known servers, sorted by friendly name."""
        return sorted(self._servers.values(), key=lambda s: s.name.lower())

    def get(self, key: str) -> DlnaServer | None:
        """Return a server by its stable key, or None."""
        return self._servers.get(key)

    async def refresh_if_stale(self) -> None:
        """Re-scan only when the last scan is older than the minimum interval.

        Keeps the root browse live (new servers appear) without hammering
        the network with an SSDP round on every folder re-open.
        """
        if time.monotonic() - self._last_refresh >= ROOT_REFRESH_MIN_INTERVAL:
            await self.refresh()

    async def refresh(self) -> None:
        """Re-scan SSDP, ensure all manual URLs and remove dead servers."""
        async with self._lock:
            self._last_refresh = time.monotonic()
            locations: set[str] = set(self._manual_urls)
            try:
                # class helper: one M-SEARCH round for MediaServer devices,
                # returns raw SSDP response header dicts.
                for headers in await DmsDevice.async_discover():
                    location = headers.get("location")
                    if location:
                        locations.add(location)
            except Exception as err:  # noqa: BLE001 - discovery must never kill browse
                self.logger.warning("DLNA: SSDP scan failed: %s", err)

            for location in locations:
                await self._ensure(location)

            # drop servers that no longer answer at their description URL
            for key in list(self._servers):
                server = self._servers[key]
                if server.location in self._manual_urls:
                    continue
                try:
                    await self._factory.async_create_device(server.location)
                except Exception:  # noqa: BLE001, S110 - gone is gone
                    self.logger.info(
                        "DLNA: media server %s (%s) is no longer reachable, dropping",
                        server.name,
                        server.location,
                    )
                    self._servers.pop(key, None)

    async def _ensure(self, location: str) -> None:
        """Add the server at a description URL if not known yet."""
        if any(s.location == location for s in self._servers.values()):
            return
        try:
            device = await self._factory.async_create_device(location)
        except Exception as err:  # noqa: BLE001 - a dead manual/SSDP entry must not fail the scan
            self.logger.warning("DLNA: could not fetch device at %s: %s", location, err)
            return
        key = server_key_from_udn(device.udn)
        if key in self._servers:
            return
        dms = DmsDevice(device, None)
        name = (
            dms.name
            or getattr(device, "friendly_name", None)
            or getattr(device, "name", None)
            or key
        )
        # the device's own icon (biggest one from its description); used as
        # the BrowseFolder image for the server's root folder. Absoluteize:
        # some servers advertise a relative icon url in their description.
        icon_url = None
        try:
            raw_icon = dms.icon
        except Exception:  # noqa: BLE001 - a broken icon must not hide the server
            raw_icon = None
        if raw_icon:
            icon_url = (
                raw_icon if raw_icon.startswith("http") else urljoin(location, raw_icon)
            )
        self._servers[key] = DlnaServer(
            key=key,
            udn=device.udn,
            name=name,
            location=location,
            dms=dms,
            icon_url=icon_url,
        )
        self.logger.info("DLNA: media server %s found at %s", name, location)
