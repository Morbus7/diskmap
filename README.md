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
