# Project Context for AI Agents

## Repository

Provider code only: `provider/dlna_music/` — a Music Assistant music provider
(domain `dlna_music`, "DLNA Media Servers"). The combined docker image build
(DLNA + VK Music edition of Music Assistant) lives in the parent project
`music-assistant-vk-edition+dlna` (`d:\src\music-assistant-vk-edition+dlna\`
on this machine).

`README.md` is written for humans/public audience — keep it free of
machine-specific and internal development details; those belong here.

## Local development environment / test bench

MA runs in the docker container `build-music-assistant-1` inside the Vagrant
VM `build-music-assistant-vk-edition` (port 8095, the vk-edition repo is
synced to `/home/vagrant/build`). A test miniDLNA runs in the VM
(`/opt/dlna-test/music`, 3 generated tones, port 8200, description URL
`http://10.0.2.15:8200/rootDesc.xml`).

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

An instance is created in the MA UI (http://localhost:8095 → Settings →
Providers → Add → "DLNA Media Servers"). The provider has NO setup flow — it
is created immediately; option values are read with `requires_reload=True`.

## Verified (2026-11-25, test stand)

- discovery via manual URL → "Test MiniDLNA"
- browse: root (server folders) → server level (Browse Folders/Music/…)
  → Music (3 tracks with correct title/duration)
- `get_stream_details` → direct URL `http://.../MediaItems/N.mp3`, the mp3
  downloads from inside the MA container (200, audio/mpeg)
- real LAN servers: `192.168.88.219:1338` and `:9080` are visible from the
  VM via SSDP (Vagrant NAT passes outgoing unicast) and their `rootDesc.xml`
  reads from inside the MA container — testing them uses the same
  manual-URL method

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

## Icons

- Provider icon in the plugins list: `icon.svg` in the provider directory —
  MA picks it up automatically (`detect_provider_icons`; optional variants
  `icon_dark.*` / `icon_monochrome.*`). MA must be restarted after adding it.
  The file is the genuine DLNA mark (svgrepo 330311), recolored to green
  `#00a651`, scaled to a 1000x1000 viewBox. Note: svgrepo.com is not
  reachable with Windows curl (TLS exit 35) — download from inside the VM.
- Server root folders show the device's native icon:
  `BrowseFolder.image = MediaItemImage(THUMB, path=server.icon_url,
  remotely_accessible=True)`; `DlnaServer.icon_url` comes from
  `DmsDevice.icon` (the largest icon in `description.xml`), relative URLs
  are absolutized with `urljoin`. Verified: rockpi4a (`/deviceIcon/1`),
  Test MiniDLNA (`/icons/lrg.png`), tornanopi2 (`/deviceIcon/1`).
