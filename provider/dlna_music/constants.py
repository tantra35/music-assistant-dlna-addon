"""Shared constants of the DLNA Music provider."""
from __future__ import annotations

from music_assistant_models.enums import ProviderFeature

# options config: newline-separated device description URLs, reachable from
# the MA host. Used in addition to (or instead of) SSDP discovery - e.g. when
# multicast does not reach the MA host (VMs, docker bridges).
CONF_SERVER_URLS = "server_urls"

# seconds between SSDP re-scans of the local network
SCAN_INTERVAL = 300

# a browse of the root triggers a re-scan only if the last scan is older
ROOT_REFRESH_MIN_INTERVAL = 60

# persistent MA-cache prefix for browsed track metadata. Entries are stored
# under this prefix (provider=instance_id) so queue items survive a provider
# restart: _track_cache/_track_parent_hints are in-memory only.
CACHE_KEY_PREFIX = "track_cache/"

SUPPORTED_FEATURES = {ProviderFeature.BROWSE}
