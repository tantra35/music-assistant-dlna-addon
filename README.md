# Music Assistant – DLNA Media Servers music provider

**A [Music Assistant](https://music-assistant.io) music provider that browses and streams audio from DLNA / UPnP-AV media servers on the local network** — miniDLNA, upmpdcli, Synology, and any other UPnP-AV compliant server. Provider domain: `dlna_music`.

This repository contains **only the provider code**. The combined docker image build (DLNA + VK Music edition of Music Assistant) lives in the parent project `music-assistant-vk-edition+dlna`.

## Features

- **Browse** DLNA/UPnP-AV media servers directly from the Music Assistant UI.
- **Dynamic discovery**: background SSDP re-scan (every 5 minutes, plus on root browse if the cache is older than a minute) and **manual device-description URLs** in the provider options.
- **Manual URLs are a first-class feature, not a workaround**: SSDP (UDP multicast `239.255.255.250:1900`) does not pass through VirtualBox NAT or docker bridge networks — there, only an explicit URL works.
- Each discovered server appears as its own **root folder with the device's native icon** (the largest icon from `description.xml`); deeper levels map 1:1 to the server's ContentDirectory tree.
- **Direct streaming**: track `res` URLs are handed to the player as-is (plain HTTP), no proxying.
- Browsed track metadata is **persisted in the MA cache**, so queue items survive a provider restart.
- Stable browse paths: `server_key` is derived from the server's UDN UUID, so paths survive server and provider restarts.

## Installation

Copy the `provider/dlna_music/` directory into the Music Assistant image as
`music_assistant/providers/dlna_music/`, then restart Music Assistant so the
manifest is picked up. See the docker build in the parent project
`music-assistant-vk-edition+dlna`.

Then create an instance in the MA UI: **Settings → Providers → Add → “DLNA Media Servers”**.
There is no setup flow — the provider is created immediately; changing an option with
`requires_reload=True` triggers a reload.

## Provider options

| Option | Type | Description |
|---|---|---|
| `server_urls` | split string (one URL per line) | Device-description URL of each server reachable from the MA host, e.g. `http://192.168.88.219:1338/rootDesc.xml`. Used in addition to SSDP discovery. |

Note: the description URL is not always `/description.xml` (miniDLNA uses
`/rootDesc.xml`) — you can find it in the `LOCATION` field of the SSDP
response or on the server's web page.

## Architecture

One provider instance. The root browse shows **one folder per discovered
server**; everything below is the server's ContentDirectory tree 1:1.

```
provider/dlna_music/
  manifest.json   domain dlna_music, BROWSE, async-upnp-client
  __init__.py     setup() + DlnaMusicProvider (init, config entries, scan loop)
  constants.py    CONF_SERVER_URLS, SCAN_INTERVAL, SUPPORTED_FEATURES
  discovery.py    ServerRegistry: SSDP + manual URLs -> cached DmsDevice
  catalog.py      browse(): root / server levels, ContentDirectory walker
  media.py        get_track / get_stream_details (direct HTTP from res)
  base.py         typing-only mixin contract (empty at runtime — MRO!)
```

Browse paths look like `{instance_id}://{server_key}/{container_id}`, where
`server_key` is the UUID from the server's UDN (stable across restarts) and
`container_id` is percent-encoded. DLNA container ids are absolute, so the
last path segment is always used; the server level itself is the root
container `"0"` (not the `server_key` — otherwise UPnP error 701).

Pagination note (MA 2.10.13): browse results are returned in full; the
frontend scrolls locally.

## Development / test bench (Vagrant `build-music-assistant-vk-edition`)

MA runs in the docker container `build-music-assistant-1` inside the VM
(port 8095, the vk-edition repo is synced to `/home/vagrant/build`). A test
miniDLNA runs in the VM (`/opt/dlna-test/music`, 3 generated tones, port
8200, description URL `http://10.0.2.15:8200/rootDesc.xml`).

Deploying the provider into the running container (ephemeral, until recreate):

```bash
# 1. copy into the synced folder (if not already there)
rm -rf d:/src/music-assistant-vk-edition/_dlna_deploy/dlna_music
cp -r provider/dlna_music d:/src/music-assistant-vk-edition/_dlna_deploy/
# 2. into the container
vagrant ssh -c "sudo docker cp /home/vagrant/build/_dlna_deploy/dlna_music/. \
  build-music-assistant-1:/app/venv/lib/python3.14/site-packages/music_assistant/providers/dlna_music/"
# 3. clear pycache + restart (so MA sees the manifest)
vagrant ssh -c "cd /home/vagrant/build && sudo docker compose restart music-assistant"
```

Offline logic checks without creating an instance (the probe runs inside the
container):

```bash
vagrant ssh -c "sudo docker cp /home/vagrant/build/_dlna_probe.py build-music-assistant-1:/tmp/ && \
  sudo docker exec build-music-assistant-1 /app/venv/bin/python /tmp/_dlna_probe.py"
```

(The `_dlna_probe.py` script and the `_dlna_deploy/` copy live in the
vk-edition repo — it is the container's synced folder; after changing the
logic, repeat steps 1–2.)

## Verified (2026-11-25, test stand)

- discovery via manual URL → “Test MiniDLNA”
- browse: root (server folders) → server level (Browse Folders/Music/…)
  → Music (3 tracks with correct title/duration)
- `get_stream_details` → direct URL `http://.../MediaItems/N.mp3`, the mp3
  downloads from inside the MA container (200, audio/mpeg)
- real LAN servers: `192.168.88.219:1338` and `:9080` are visible from the
  VM via SSDP (Vagrant NAT passes outgoing unicast) and their `rootDesc.xml`
  reads from inside the MA container — testing them uses the same
  manual-URL method

## Icons

- **Provider icon** in the plugins list: `icon.svg` in the provider directory —
  MA picks it up automatically (`detect_provider_icons`; optional variants
  `icon_dark.*` / `icon_monochrome.*`). MA must be restarted after adding it.
  The file is the genuine DLNA mark (svgrepo 330311), recolored to green
  `#00a651`, scaled to a 1000x1000 viewBox.
- **Server root folders** show the device's native icon:
  `BrowseFolder.image = MediaItemImage(THUMB, path=server.icon_url,
  remotely_accessible=True)`; `DlnaServer.icon_url` comes from
  `DmsDevice.icon` (the largest icon in `description.xml`), relative URLs are
  absolutized with `urljoin`.

## Known pitfalls

- `UpnpFactory(requester)` in async-upnp-client 0.48 requires a requester:
  use `UpnpFactory(AiohttpRequester())`.
- `DmsDevice.BrowseResult.result` is an **already parsed** list of
  `didl_lite` objects — do not call `from_xml_string` on it a second time.
- `BrowseFolder` requires keyword-only `provider=instance_id`.
- The server level in the browse path is container `"0"`, not `server_key`
  (UPnP error 701 otherwise).
- Mixins must come before `MusicProvider` in the base list: the contract
  class is empty at runtime (MRO pitfall).
