"""Build all outputs: print maps, station tables and web data, plus a change report."""

import io
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import MultiPolygon, box
from shapely.geometry.polygon import orient

from .basemap import countries as gisco_countries
from .config import ISO_TO_GISCO, MEMBERS, ROOT, TERRITORIES, THEME_LABEL
from .data import fetch_stations
from .layout import plan_country
from .ocean import attach_ocean_geometry, fetch_ocean_geometry
from .overview import render_overview
from .render import render_panel, setup_fonts

TABLE_COLUMNS = {
    "map_number": "Map number",
    "name": "Station name",
    "id": "Station abbreviation",
    "theme_label": "Station type",
    "site_type": "Site type",
    "cls": "Station class",
    "host": "Host institute",
    "labeled": "Labelling date",
}
COMPARE_FIELDS = ["name", "theme", "cls", "labeled", "lat", "lon", "host"]


def load_network(refresh: bool) -> gpd.GeoDataFrame:
    stations = attach_ocean_geometry(fetch_stations(refresh), fetch_ocean_geometry(refresh))
    stations["theme_label"] = stations["theme"].map(THEME_LABEL)
    code_to_member = {code: cc for cc in MEMBERS for code in TERRITORIES.get(cc, [cc])}
    stations["member"] = stations["country"].map(code_to_member).fillna("")
    return stations


def number_stations(st: gpd.GeoDataFrame) -> dict:
    """Alphabetical numbering of a country's mapped stations, as in the handbook tables."""
    mapped = st[st["has_geometry"]].sort_values(["name", "theme"])
    return {sid: i + 1 for i, sid in enumerate(mapped["id"])}


def write_table(st: gpd.GeoDataFrame, numbers: dict, path: Path):
    df = pd.DataFrame(st.drop(columns="geometry"))
    df["map_number"] = df["id"].map(numbers).astype("Int64")
    df = df.sort_values(["map_number", "name"], na_position="last")
    path.parent.mkdir(parents=True, exist_ok=True)
    df[list(TABLE_COLUMNS)].rename(columns=TABLE_COLUMNS).to_csv(path, index=False)


def diff_report(old_path: Path, new: gpd.GeoDataFrame) -> list[str]:
    if not old_path.exists():
        return ["First build: no previous station list to compare with."]
    old = pd.read_csv(old_path, dtype=str, keep_default_na=False).set_index("uri")
    cur = pd.read_csv(io.StringIO(pd.DataFrame(new.drop(columns="geometry")).to_csv(index=False)), dtype=str, keep_default_na=False).set_index("uri")
    lines = []
    for uri in cur.index.difference(old.index):
        lines.append(f"+ added   {cur.at[uri, 'id']} ({cur.at[uri, 'name']}, {cur.at[uri, 'country']}, {cur.at[uri, 'theme']})")
    for uri in old.index.difference(cur.index):
        lines.append(f"- removed {old.at[uri, 'id']} ({old.at[uri, 'name']}, {old.at[uri, 'country']})")
    for uri in cur.index.intersection(old.index):
        for f in COMPARE_FIELDS:
            a, b = old.at[uri, f], cur.at[uri, f]
            if f in ("lat", "lon") and a and b and abs(float(a) - float(b)) < 1e-4:
                continue
            if str(a) != str(b):
                lines.append(f"~ changed {cur.at[uri, 'id']}: {f} {a!r} -> {b!r}")
    return lines or ["No changes in the station list since the previous build."]


def build(out: Path, countries: list[str], formats: list[str], refresh: bool, overview: bool = True):
    setup_fonts()
    stations = load_network(refresh)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    web = out / "web"
    changes = diff_report(web / "stations.csv", stations)

    # A partial build (some countries only) updates the existing site rather than replacing it.
    old_manifest = json.loads((web / "manifest.json").read_text()) if (web / "manifest.json").exists() else {}
    old_tables = json.loads((web / "tables.json").read_text()) if (web / "tables.json").exists() else {}
    manifest = {"generated": generated, "n_stations": int(len(stations[stations["member"] != ""])),
                "overview": old_manifest.get("overview"), "countries": old_manifest.get("countries", {})}
    tables = {k: v for k, v in old_tables.items() if k in MEMBERS}
    all_numbers = {}
    for cc in MEMBERS:
        all_numbers.update(number_stations(stations[stations["member"] == cc]))

    for cc in countries:
        st = stations[stations["member"] == cc]
        numbers = number_stations(st)
        mapped = st[st["has_geometry"]]
        panels = plan_country(cc, mapped)
        entry = {"name": MEMBERS[cc], "stations": int(len(st)),
                 "by_theme": {t: int((st["theme"] == t).sum()) for t in ("atmosphere", "ecosystem", "ocean")},
                 "unmapped": st.loc[~st["has_geometry"], "id"].tolist(), "panels": []}
        for p in panels:
            base = out / "print" / cc / f"{cc}_{p.key}_{p.kind}"
            render_panel(p, cc, mapped, numbers, base, formats)
            entry["panels"].append({"key": p.key, "kind": p.kind, "title": panel_title(p, MEMBERS[cc], st),
                                    "stations": p.station_ids, "files": {f: f"maps/{cc}/{base.name}.{f}" for f in formats}})
            print(f"  {cc} panel {p.key} ({p.kind}): {len(p.station_ids)} stations")
        write_table(st, numbers, out / "print" / cc / f"{cc}_stations.csv")
        tables[cc] = table_rows(st, numbers)
        manifest["countries"][cc] = entry

    if overview:
        render_overview(stations[stations["member"] != ""], out / "print" / "ICOS_station_network", formats)
        manifest["overview"] = {f: f"maps/ICOS_station_network.{f}" for f in formats}
        print("  overview map")

    write_site(out, web, stations, all_numbers, manifest, tables)
    (out / "CHANGES.txt").write_text(f"Build {generated}\n" + "\n".join(changes) + "\n")
    print("\n".join(changes))


def panel_title(panel, country_name: str, st: gpd.GeoDataFrame) -> str:
    names = st.set_index("id").loc[panel.station_ids, "name"].tolist()
    if panel.kind == "home":
        return country_name
    if panel.kind == "remote":
        return "Remote stations: " + ", ".join(names)
    return "Ocean stations and Ship of Opportunity lines"


def table_rows(st: gpd.GeoDataFrame, numbers: dict) -> list[dict]:
    df = pd.DataFrame(st.drop(columns="geometry"))
    df["map_number"] = df["id"].map(numbers)
    df = df.sort_values(["map_number", "name"], na_position="last")
    cols = [*TABLE_COLUMNS, "theme", "uri"]
    return [{k: (None if pd.isna(v) else (int(v) if k == "map_number" else v)) for k, v in row.items()}
            for row in df[cols].to_dict("records")]


def _clockwise(g):
    if g.geom_type == "Polygon":
        return orient(g, -1.0)
    if g.geom_type == "MultiPolygon":
        return MultiPolygon([orient(p, -1.0) for p in g.geoms])
    return g


def europe_countries() -> gpd.GeoDataFrame:
    """Simplified country outlines for the front-page map, wound clockwise as d3-geo expects."""
    world = gpd.clip(gisco_countries("20"), box(-32, 26, 46, 82))
    gisco_to_iso = {ISO_TO_GISCO.get(cc, cc): cc for cc in MEMBERS}
    world = world.assign(member=world["CNTR_ID"].map(gisco_to_iso).fillna(""))
    world["geometry"] = world.geometry.simplify(0.02).apply(_clockwise)
    return world[world.geometry.geom_type.isin(["Polygon", "MultiPolygon"])][["CNTR_ID", "NAME_ENGL", "member", "geometry"]]


def write_site(out: Path, web: Path, stations, all_numbers, manifest, tables):
    """Static website: the app from web/, the maps, and the data it reads."""
    web.mkdir(parents=True, exist_ok=True)
    for f in (ROOT / "web").iterdir():
        if f.is_file():
            shutil.copy(f, web / f.name)
    if (out / "print").exists():
        shutil.copytree(out / "print", web / "maps", dirs_exist_ok=True, ignore=shutil.ignore_patterns("*.csv"))
        for csv in (out / "print").glob("*/*_stations.csv"):
            shutil.copy(csv, web / "maps" / csv.parent.name / csv.name)
    pub = stations.copy()
    pub["map_number"] = pub["id"].map(all_numbers).astype("Int64")
    pub = pub[pub["has_geometry"]].drop(columns=["has_geometry"])
    pub.to_file(web / "stations.geojson", driver="GeoJSON")
    # Full list including stations without geometry; the next build diffs against it.
    pd.DataFrame(stations.drop(columns="geometry")).to_csv(web / "stations.csv", index=False)
    europe_countries().to_file(web / "countries.geojson", driver="GeoJSON", COORDINATE_PRECISION=3)
    (web / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    (web / "tables.json").write_text(json.dumps(tables, ensure_ascii=False))
