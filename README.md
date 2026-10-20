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
| Stations not yet labelled (no production station yet), PIs of candidates | Labelling application entries (graph `stationentry`), same endpoint |
| Labelling status and date | Labelling application (graph `stationlabeling`): `STEP3APPROVED` = labelled, its status date = labelling date |
| Ocean SOOP routes and fixed ocean station positions | ICOS ocean Zarr store, `https://zarr.icos-cp.eu/icos-socat.zarr` (cruises from the last `TRACK_YEARS` years) |
| Country boundaries | Eurostat GISCO, 1:3M for country maps (© EuroGeographics) |
| Climate zone (Köppen-Geiger) | Carbon Portal where present; otherwise read at the station position from the 1 km map for 1991–2020 of [Beck et al. (2023)](https://doi.org/10.6084/m9.figshare.21789074) (CC BY 4.0), marked with * |

Stations of class 1, 2 and Associated count as part of the network (`NETWORK_CLASSES` in
[config.py](src/icos_maps/config.py)), plus labelling-application entries that have no production
station yet. Every station gets a status from the labelling application: "Labelled" (with the date of
approval), "In labelling: step …", or "Not yet labelled", shown in the tables, popups and the website.
The few stations without a labelling entry keep the labelling date of the production metadata.
Stations run by a member country other than the one they stand in are listed in `OPERATED_BY` in
[config.py](src/icos_maps/config.py) (Welgegund → Finland, Yangambi and La Réunion → Belgium): they
appear on that member's maps and tables, in a remote panel that shades the host country grey. Downloads are cached in `cache/`; `--refresh` fetches them again.

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
downloads and a station table. A **Stations** tab on the front page (`#/stations`) lists all stations.
Station tables show coordinates, elevation and climate zone (NA for ship lines), sort by any column,
filter per column (text anywhere; numbers and dates also `>500`, `<2020`, `100-500`) and download the
rows shown as CSV, XLSX or KML. Links are shareable (`#/world`, `#/FR`, `#/FR/stations`, `#/FR/maps` for the figures,
`#/FR/detailed` for the detailed map, which adds `@lat,lon,zoomz` as you pan and zoom).
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

Country pages can switch from the figures to a **detailed map**: an interactive MapTiler Cloud map
(Web Mercator, `MAPTILER_STYLE`, default `topo-v2`) with the stations, SOOP lines and popups, where the
remote and ocean panels stay fixed as insets while the main map pans and zooms; clicking an inset flies
there. It appears when `MAPTILER_KEY` is set in `.env`; browsers get the key from `/api/config`, so
restrict it to the site's domain in the MapTiler dashboard. The figures keep their own projections.
For the Netherlands, the detailed map shows the national TOPraster maps (Kadaster/PDOK WMS, CC0) from
zoom 8.5 inwards, TOP250raster to TOP25raster by zoom level (`DETAIL_OVERLAYS` in
[web/app.js](web/app.js); other countries' national maps can be added there).

The front-page map and the detailed maps have **Labelled / In labelling / Planned** toggles (Labelled
and In labelling on by default): "In labelling" are stations part-way through the labelling steps, "Planned" the rest
that are not labelled yet. The print figures always show all stations.

A partial build (`icos-maps FR`) updates the existing site instead of replacing it. The GitHub Actions
workflow in [.github/workflows/maps.yml](.github/workflows/maps.yml) rebuilds every night and on
demand, and lists the changes in the run summary.

## Running with Docker

```
docker compose up -d --build   # site on 127.0.0.1:8120; set BIND / PORT / API_TOKEN in .env
docker compose logs -f api
```

The `api` container builds the maps on start and then every day at `BUILD_AT` (UTC, default 03:00),
and on request through the REST API. Each build is published as a new release and switched in
atomically; the last three are kept, and a failed build leaves the previous site online. `web` is
nginx serving the current release and proxying `/api/`. The change report of each build is at
`/CHANGES.txt` on the site.

Production: VM 117 (zarr-tools, 10.10.10.153) in `/opt/icosmaps` with `BIND=10.10.10.153`; Caddy on
fsicos4 publishes it as https://icosmaps.fs4vm.icos-cp.eu. To deploy a new version:
`cd /opt/icosmaps && git pull && docker compose up -d --build --remove-orphans`. When
`docker/nginx.conf` changed, also run `docker compose up -d --force-recreate web`: the file is
bind-mounted, and `git pull` replaces it with a new file the running container does not see.
The API token is `API_TOKEN` in `/opt/icosmaps/.env` (mode 600).

## REST API

Interactive documentation at `/api/docs` (OpenAPI at `/api/openapi.json`).

| Endpoint | |
|---|---|
| `GET /api/status` | published release, build time, station count, next scheduled build, running build, change report |
| `GET /api/countries`, `GET /api/countries/{cc}` | panels and file URLs; one country with its station table |
| `GET /api/maps/{cc}/{panel}.{png,svg,pdf}` | one map; `?dpi=72–600` (PNG) and `?marker_scale=0.5–3` render it on request and cache it until the next build, default options redirect to the published file |
| `POST /api/builds` | start a build: `{"countries": ["FR"], "refresh": true}` (empty list = all); needs `Authorization: Bearer $API_TOKEN` |
| `GET /api/builds`, `GET /api/builds/{id}` | recent builds; one build with the end of its log |

```
curl -X POST https://icosmaps.fs4vm.icos-cp.eu/api/builds -H "Authorization: Bearer $API_TOKEN" \
     -H "Content-Type: application/json" -d '{"countries": ["FR"]}'
curl -o fr.png "https://icosmaps.fs4vm.icos-cp.eu/api/maps/FR/a.png?dpi=150&marker_scale=1.5"
```

Builds over the API are disabled when `API_TOKEN` is not set.

## Known gaps in the source data

- Ecosystem stations have no responsible organisation in the metadata, so the "Host institute" column is
  empty for them.
- Ocean stations without data in the Zarr store (currently UK-Caribbean, Polarstern, Atlantic Sail,
  Belgica, Celtic Explorer) appear in the tables without a map number; see `unmapped` in the manifest.

## License

GPL-3.0, see [LICENSE](LICENSE). The bundled Open Sans fonts are under the SIL Open Font License
([assets/fonts/OFL.txt](assets/fonts/OFL.txt)).
