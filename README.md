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
| Ocean SOOP routes and fixed ocean station positions | ICOS ocean Zarr store, `https://zarr.icos-cp.eu/icos-socat.zarr` (cruises from the last `TRACK_YEARS` years) |
| Country boundaries | Eurostat GISCO, 1:3M for country maps (© EuroGeographics) |

Stations of class 1, 2 and Associated count as part of the network (`NETWORK_CLASSES` in
[config.py](src/icos_maps/config.py)). Downloads are cached in `cache/`; `--refresh` fetches them again.

## Output (`out/`)

```
print/ICOS_station_network.{svg,pdf,png}  overview map (handbook page 5)
print/<CC>/<CC>_a_home.*                  home territory
print/<CC>/<CC>_b_remote.*                overseas / remote stations (Réunion, Guiana, Svalbard, Greenland, Canaries)
print/<CC>/<CC>_c_ocean.*                 SOOP routes and offshore fixed ocean stations
print/<CC>/<CC>_stations.csv              station table, same numbers as on the map
web/stations.geojson                      all mapped stations with their map numbers
web/manifest.json                         build time, panels and files per country, stations without geometry
web/index.html                            example interactive map for the website (Leaflet, reads stations.geojson)
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

The website can either embed the generated PNG/SVG maps (stable paths in `web/manifest.json`) or draw
its own interactive map from `web/stations.geojson`; [web/index.html](web/index.html) is a minimal
example. The GitHub Actions workflow in [.github/workflows/maps.yml](.github/workflows/maps.yml)
rebuilds every night and on demand, and lists the changes in the run summary. Point its output at
wherever the website reads from, such as a static bucket or GitHub Pages.

## Known gaps in the source data

- Ecosystem stations have no responsible organisation in the metadata, so the "Host institute" column is
  empty for them.
- Ocean stations without data in the Zarr store (currently UK-Caribbean, Polarstern, Atlantic Sail,
  Belgica, Celtic Explorer) appear in the tables without a map number; see `unmapped` in the manifest.
