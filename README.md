# ICOS station maps

Generates the ICOS station network maps (the handbook overview map and the per-country maps with
numbered stations) plus the matching station tables and web data, straight from the Carbon Portal.
It replaces the manual ArcInfo workflow: rerun it whenever the station list changes.

```
uv run icos-maps                 # all 16 member countries + overview
uv run icos-maps CH FR --refresh # selected countries, re-download metadata and ocean tracks
uv run icos-maps --formats svg   # svg / pdf / png (default: all three)
```

## Sources

| What | Source |
|---|---|
| Stations: position, domain, class, labelling date, host, ecosystem type | Carbon Portal SPARQL, `https://meta.icos-cp.eu/sparql` |
| Stations not yet labelled (no production station yet) | Labelling application entries (graph `stationentry`), same endpoint |
| Ocean SOOP routes and fixed ocean station positions | ICOS ocean Zarr store, `https://zarr.icos-cp.eu/icos-socat.zarr` (cruises from the last `TRACK_YEARS` years) |
| Country boundaries | Eurostat GISCO, 1:3M for country maps (© EuroGeographics) |

Stations of class 1, 2 and Associated count as part of the network (`NETWORK_CLASSES` in
[config.py](src/icos_maps/config.py)), plus labelling-application entries that have no production
station yet. Every station gets a status, "Labelled" (it has a labelling date) or "Not yet labelled",
shown in the tables and the website. Downloads are cached in `cache/`; `--refresh` fetches them again.

## Output (`out/`)

```
print/ICOS_station_network.{svg,pdf,png}  overview map (handbook page 5)
print/<CC>/<CC>_a_home.*                  home territory
print/<CC>/<CC>_b_remote.*                overseas / remote stations (Réunion, Guiana, Svalbard, Greenland, Canaries)
print/<CC>/<CC>_c_ocean.*                 SOOP routes and offshore fixed ocean stations
print/<CC>/<CC>_stations.csv              station table, same numbers as on the map
web/                                      static website (serve this folder), see below
CHANGES.txt                               stations added / removed / changed since the previous build
```

Panels are chosen automatically: a country gets a remote panel only when it has stations far from its
home territory, and an ocean panel only when it has SOOP lines or fixed ocean stations offshore.
Stations are numbered alphabetically per country, as in the handbook tables.

## Editing the maps

The SVG and PDF files are meant to be finished in Illustrator or Inkscape:

- text stays text (Open Sans, embedded in the PDF), not outlines;
- every layer is a named group: `other-countries`, `focus-country`, `soop-<station>`, `stations-<domain>`,
  `number-<station>`, `leader`, `locator`, `scale-bar`, `north-arrow`, `legend`, `credit`;
- markers that would overlap are spread apart with a leader line to the true position. Move them freely.

Colours, the multi-domain distance and the track window are set in [config.py](src/icos_maps/config.py).

## Website

`out/web/` is a self-contained static site, built from [web/](web/): a front page with a Europe and a
World view (the latter shows the stations in Africa, South America and overseas territories, and lists
them in the side panel), where you click a member country (or pick one from the dropdown), then that country's map panels with SVG/PDF/PNG
downloads and a sortable, filterable station table. Links are shareable (`#/world`, `#/FR`, `#/FR/stations`).
Serve the folder with any web server, e.g. `python -m http.server -d out/web`.

It reads these files, which other sites can use too:

| File | Content |
|---|---|
| `manifest.json` | build time, counts, panels and file paths per country, stations without geometry |
| `tables.json` | station table rows per country |
| `stations.geojson` | all mapped stations (points and SOOP lines) with their map numbers |
| `countries.geojson` | simplified European country outlines for the front-page map |
| `world.geojson` | coarse world outlines for the World view |
| `maps/` | all map files and station CSVs |

A partial build (`icos-maps FR`) updates the existing site instead of replacing it. The GitHub Actions
workflow in [.github/workflows/maps.yml](.github/workflows/maps.yml) rebuilds every night and on
demand, and lists the changes in the run summary.

## Running with Docker

```
docker compose up -d --build   # site on 127.0.0.1:8120; set BIND / PORT in .env to change
docker compose logs -f builder
```

The `builder` container builds the maps on start and then every day at `BUILD_AT` (UTC, default
03:00). Each build is published as a new release and switched in atomically; the last three are kept,
and a failed build leaves the previous site online. `web` is nginx serving the current release.
The change report of each build is at `/CHANGES.txt` on the site.

Production: VM 117 (zarr-tools, 10.10.10.153) in `/opt/icosmaps` with `BIND=10.10.10.153`; Caddy on
fsicos4 publishes it as https://icosmaps.fs4vm.icos-cp.eu. To deploy a new version:
`cd /opt/icosmaps && git pull && docker compose up -d --build`.

## Known gaps in the source data

- Ecosystem stations have no responsible organisation in the metadata, so the "Host institute" column is
  empty for them.
- Ocean stations without data in the Zarr store (currently UK-Caribbean, Polarstern, Atlantic Sail,
  Belgica, Celtic Explorer) appear in the tables without a map number; see `unmapped` in the manifest.

## License

GPL-3.0, see [LICENSE](LICENSE). The bundled Open Sans fonts are under the SIL Open Font License
([assets/fonts/OFL.txt](assets/fonts/OFL.txt)).
