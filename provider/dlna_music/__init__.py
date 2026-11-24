"""DLNA Music provider for Music Assistant: browse and stream audio from
DLNA/UPnP media servers on the local network.

The provider is ONLINE-ONLY (browse feature): the root browse level holds
one folder per discovered media server, deeper levels map 1:1 to the
server's ContentDirectory tree, and every audio item resolves to its direct
HTTP URL at playback time. Discovery is dual-source: periodic SSDP scans
plus manually configured device description URLs (for networks where
multicast does not reach the MA host - VMs, docker bridges).

Implementation layout (mirrors the vk_music provider):
- discovery.py: ServerRegistry (SSDP + manual URLs -> DmsDevice cache)
- catalog.py:   browse routing (root folders, ContentDirectory walking)
- media.py:     get_track / get_stream_details on the browse cache
- base.py:      typing-only cross-mixin contract (empty at runtime)
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from music_assistant.models.music_provider import MusicProvider
from music_assistant_models.config_entries import ConfigEntry, ConfigEntryType

from .catalog import CatalogBrowseMixin
from .constants import CONF_SERVER_URLS, SCAN_INTERVAL, SUPPORTED_FEATURES
from .discovery import ServerRegistry
from .media import MediaApiMixin

if TYPE_CHECKING:
    from music_assistant import MusicAssistant
    from music_assistant.models import ProviderInstanceType
    from music_assistant_models.config_entries import ProviderConfig
    from music_assistant_models.provider import ProviderManifest


async def setup(
    mass: MusicAssistant, manifest: ProviderManifest, config: ProviderConfig
) -> ProviderInstanceType:
    """Initialize the provider."""
    return DlnaMusicProvider(mass, manifest, config, SUPPORTED_FEATURES)  # type: ignore[arg-type]


class DlnaMusicProvider(CatalogBrowseMixin, MediaApiMixin, MusicProvider):
    """Browse and stream audio from local DLNA media servers."""

    _registry: ServerRegistry
    _track_cache: dict[str, dict]
    _track_parent_hints: dict[str, str]
    _scan_task: asyncio.Task

    @property
    def is_streaming_provider(self) -> bool:
        """Items are streamed from remote URLs, not from local files."""
        return True

    async def get_config_entries(self) -> tuple[ConfigEntry, ...]:
        """Return the options entries (manual server description URLs)."""
        return (
            ConfigEntry(
                key=CONF_SERVER_URLS,
                type=ConfigEntryType.SPLITTED_STRING,
                label="DLNA-серверы (description.xml URL)",
                description=(
                    "По одному URL описания устройства на строку, "
                    "например http://192.168.88.10:8200/description.xml. "
                    "Используется в дополнение к SSDP-поиску — выручает, "
                    "когда multicast не доходит до хоста Music Assistant "
                    "(VM, docker bridge)."
                ),
                # SPLITTED_STRING carries ONE (newline-separated) string;
                # a list default fails config validation
                default_value="",
                required=False,
                requires_reload=True,
            ),
        )

    async def handle_async_init(self) -> None:
        """Build the server registry, run the first scan, start the loop."""
        raw_urls = self.get_config_value(CONF_SERVER_URLS) or ""
        if isinstance(raw_urls, list):
            # defensive: a value persisted before the SPLITTED_STRING fix
            urls = [str(u) for u in raw_urls]
        else:
            urls = str(raw_urls).splitlines()
        self._registry = ServerRegistry(urls, self.logger)
        self._track_cache = {}
        self._track_parent_hints = {}
        await self._registry.refresh()
        self._scan_task = asyncio.create_task(self._scan_loop())

    async def _scan_loop(self) -> None:
        """Periodic SSDP re-scan until the provider is unloaded."""
        while not self.unloading:
            await asyncio.sleep(SCAN_INTERVAL)
            if self.unloading:
                return
            try:
                await self._registry.refresh()
            except Exception as err:  # noqa: BLE001 - a bad scan must not kill the loop
                self.logger.warning("DLNA: periodic scan failed: %s", err)
