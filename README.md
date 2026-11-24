# music-assistant-dlna-addon

Music Assistant **music provider** «DLNA Media Servers» (domain `dlna_music`):
браузинг и стриминг аудио с DLNA/UPnP-AV медиасерверов локальной сети
(miniDLNA, upmpdcli, Synology, т.д.). Репозиторий содержит ТОЛЬКО код
плагина; сборка комбинированного docker-образа (DLNA + VK Music) живёт в
родительском каталоге `music-assistant-vk-edition+dlna`.

## Структура

```
provider/dlna_music/     код провайдера (manifest.json, discovery, browse, media)
```

Для запуска плагин копируется в
`music_assistant/providers/dlna_music/` внутри MA-образа — см. docker-сборку
в `d:\src\music-assistant-vk-edition+dlna\`.

## Архитектура

Один инстанс провайдера; рут-брауз = **по папке на каждый найденный сервер**,
глубже — 1:1 дерево ContentDirectory сервера. Список серверов динамический:
фоновый SSDP-пересканирование (раз в 5 мин + при открытии рута, если кеш
старше минуты) плюс **ручные URL** описаний устройств в опциях провайдера.

Ручные URL — первоклассная фича, не костыль: SSDP (UDP multicast
239.255.255.250:1900) не проходит ни через VirtualBox NAT, ни через docker
bridge — там работает только явный URL. URL описания устройства не
обязательно `/description.xml` (у miniDLNA это `/rootDesc.xml`) — узнать
можно из LOCATION в SSDP-ответе или веб-страницей сервера.

```
provider/dlna_music/
  manifest.json   домен dlna_music, BROWSE, async-upnp-client
  __init__.py     setup() + DlnaMusicProvider (init, конфиг-энтрии, scan-loop)
  constants.py    CONF_SERVER_URLS, SCAN_INTERVAL, SUPPORTED_FEATURES
  discovery.py    ServerRegistry: SSDP + manual URLs -> кеш DmsDevice
  catalog.py      browse(): рут/уровни сервера, ContentDirectory walker
  media.py        get_track / get_stream_details (прямой HTTP из res)
  base.py         typing-only контракт миксинов (пустой в runtime — MRO!)
```

Пути браузинга: `{instance_id}://{server_key}/{container_id}`, где
`server_key` = uuid из UDN сервера (стабилен, выживает рестарты), container_id
percent-encoded (DLNA-шные container id абсолютны, поэтому всегда брауется
последний сегмент; уровень сервера = корневой контейнер «0»).

Пагинация MA 2.10.13: browse отдаётся целиком (фронт скроллит локально).

## Опции провайдера

`server_urls` (SPLITTED_STRING, по URL на строку): описание устройства
каждого сервера, доступного с хоста MA, например
`http://192.168.88.219:1338/rootDesc.xml`. Используется вместе с SSDP.

## Тестовый стенд (Vagrant build-music-assistant-vk-edition)

MA живёт в docker-контейнере `build-music-assistant-1` в VM (порт 8095,
репо vk-edition синкается в /home/vagrant/build). В VM поднят тестовый
miniDLNA (`/opt/dlna-test/music`, 3 сгенерированных тона, port 8200,
description URL `http://10.0.2.15:8200/rootDesc.xml`).

Деплой провайдера в бегущий контейнер (эфемерно, до recreate):

```bash
# 1. копия в synced-folder (если ещё не там)
rm -rf d:/src/music-assistant-vk-edition/_dlna_deploy/dlna_music
cp -r provider/dlna_music d:/src/music-assistant-vk-edition/_dlna_deploy/
# 2. внутрь контейнера
vagrant ssh -c "sudo docker cp /home/vagrant/build/_dlna_deploy/dlna_music/. \
  build-music-assistant-1:/app/venv/lib/python3.14/site-packages/music_assistant/providers/dlna_music/"
# 3. чистка pycache + рестарт (чтобы MA увидел manifest)
vagrant ssh -c "cd /home/vagrant/build && sudo docker compose restart music-assistant"
```

Оффлайн-проверка логики без создания инстанса (probe бежит в контейнере):

```bash
vagrant ssh -c "sudo docker cp /home/vagrant/build/_dlna_probe.py build-music-assistant-1:/tmp/ && \
  sudo docker exec build-music-assistant-1 /app/venv/bin/python /tmp/_dlna_probe.py"
```

(скрипт `_dlna_probe.py` и копия `_dlna_deploy/` лежат в репо vk-edition —
это synced-folder контейнера; меняется логика → повторить шаги 1–2.)

Инстанс создаётся в UI http://localhost:8095 → Настройки → Провайдеры →
Добавить → «DLNA Media Servers», затем в опциях вписать server_urls.
Setup flow у провайдера НЕТ (создаётся сразу) — значения берутся из опций
с requires_reload=True.

## Проверено (2026-11-25, stand)

- discovery по ручному URL → «Test MiniDLNA»
- browse: рут (папки серверов) → уровень сервера (Browse Folders/Music/...)
  → Music (3 трека с правильными title/duration)
- get_stream_details → прямой URL `http://.../MediaItems/N.mp3`, mp3
  скачивается изнутри MA-контейнера (200, audio/mpeg)
- реальные серверы сети: 192.168.88.219:1338 и :9080 видны из VM по SSDP
  (Vagrant NAT пропускает исходящий unicast) и их rootDesc.xml читается
  из MA-контейнера — тест на них делается тем же manual-URL способом

## Иконки

- **Иконка провайдера** в списке плагинов: `icon.svg` в каталоге провайдера —
  MA сам подхватывает (`detect_provider_icons`, варианты `icon_dark.*` /
  `icon_monochrome.*` опционально). Нужен рестарт MA после добавления.
  Файл — настоящий знак DLNA (svgrepo 330311), перекрашен в зелёный
  #00a651. Внимание: svgrepo.com недоступен с Windows-curl (TLS exit 35) —
  качать из VM.
- **Корневые папки серверов** показывают родную иконку устройства:
  `BrowseFolder.image = MediaItemImage(THUMB, path=server.icon_url,
  remotely_accessible=True)`; `DlnaServer.icon_url` берётся из
  `DmsDevice.icon` (самая крупная иконка из description.xml), относительные
  URL абсолютизируются через urljoin. Проверено: rockpi4a
  (`/deviceIcon/1`), Test MiniDLNA (`/icons/lrg.png`), tornanopi2
  (`/deviceIcon/1`).

## Грабли

- `UpnpFactory(requester)` в 0.48 требует requester: `UpnpFactory(AiohttpRequester())`.
- `DmsDevice.BrowseResult.result` — УЖЕ распарсенный список didl_lite
  объектов; второй раз from_xml_string не звать.
- `BrowseFolder` требует keyword-only `provider=instance_id`.
- Уровень сервера в пути — это контейнер «0», не server_key (UPnP 701).
- Миксины до MusicProvider в bases: contract-класс пустой в runtime
  (детали — скилл vk-music-dev, MRO pitfall).
