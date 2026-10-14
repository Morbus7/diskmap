# Diskmap

Viser hva som tar plass på disker (omtrent som TreeSize), i Home Assistant og X2.

- `agent/`: liten skanner som kjører i Docker på hver maskin. Den leser bare mappeinformasjon, åpner aldri filer og har disken montert read-only.
- `custom_components/diskmap/`: Home Assistant-integrasjon (HACS). Henter data fra agentene og lager sensorer.
- `deploy/`: ferdige compose-filer for Synology (Container Manager) og Portainer.

## Agentens API (krever `Authorization: Bearer <API_TOKEN>`)

| Kall | Svar |
|---|---|
| `GET /api/info` | navn, versjon, røtter |
| `GET /api/summary` | kapasitet, skannetidspunkt, skanne-id, toppmapper med størrelse og vekst |
| `GET /api/tree` | fullt tre, største filer, filtyper (gzip). `?path=volume1/photo&depth=2` gir et utsnitt |
| `GET /api/status` | pågående skanning med fremdrift |
| `POST /api/scan` | start skanning (202 = startet, 409 = kjører allerede) |
| `GET /healthz` | uten token, bare for Docker |

Noder i treet: `n` navn, `t` type (`d` mappe, `f` fil, `o` sammenslåtte mindre elementer), `s` byte på disk,
`f` antall filer, `g` vekst i byte siden forrige skanning, `new` ny siden sist, `k` antall sammenslåtte, `c` barn.

## Home Assistant-integrasjonen

Legg til via HACS (egendefinert arkiv `Morbus7/diskmap`, type Integration), eller kopier `custom_components/diskmap` til `/config/custom_components/`.
Deretter: Innstillinger → Enheter og tjenester → Legg til → Diskmap. Én oppføring per agent (navn, adresse, port, token).
Adresse, port og token kan endres senere med «Konfigurer på nytt».

- Sensorer per rot: brukt, ledig, total, brukt prosent, ikke synlig. Én sensor per toppmappe (størrelse, med `growth`, `files` og `share` som attributter).
- `binary_sensor.<agent>_scanning`, `button.<agent>_scan_now` og `sensor.<agent>_last_scan`.
- Tjenester: `diskmap.scan` (én eller alle agenter) og `diskmap.get_tree` (svar med en del av treet: `path`, `depth`).
- Hendelse `diskmap_scan_finished` når en ny skanning er hentet.
- Websocket for visninger (bare administratorer): `diskmap/agents`, `diskmap/tree`, `diskmap/files`, `diskmap/types`, `diskmap/scan`.

Tester: `pytest --allow-hosts=127.0.0.1` med en agent som kjører lokalt (se `tests/test_live_agent.py`).
