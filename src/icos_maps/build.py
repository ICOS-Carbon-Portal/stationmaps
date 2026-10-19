"""Build all outputs: print maps, station tables and web data, plus a change report."""

import io
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd

from .config import MEMBERS, ROOT, TERRITORIES, THEME_LABEL
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

    manifest = {"generated": generated, "n_stations": int(len(stations[stations["member"] != ""])), "countries": {}}
    all_numbers = {}
    for cc in countries:
        st = stations[stations["member"] == cc]
        numbers = number_stations(st)
        all_numbers.update(numbers)
        mapped = st[st["has_geometry"]]
        panels = plan_country(cc, mapped)
        entry = {"name": MEMBERS[cc], "stations": int(len(st)), "unmapped": st.loc[~st["has_geometry"], "id"].tolist(), "panels": []}
        for p in panels:
            base = out / "print" / cc / f"{cc}_{p.key}_{p.kind}"
            render_panel(p, cc, mapped, numbers, base, formats)
            entry["panels"].append({"key": p.key, "kind": p.kind, "stations": p.station_ids,
                                    "files": [str(base.relative_to(out)) + f".{f}" for f in formats]})
            print(f"  {cc} panel {p.key} ({p.kind}): {len(p.station_ids)} stations")
        write_table(st, numbers, out / "print" / cc / f"{cc}_stations.csv")
        manifest["countries"][cc] = entry

    if overview:
        render_overview(stations[stations["member"] != ""], out / "print" / "ICOS_station_network", formats)
        print("  overview map")

    web.mkdir(parents=True, exist_ok=True)
    pub = stations.copy()
    pub["map_number"] = pub["id"].map(all_numbers).astype("Int64")
    pub = pub[pub["has_geometry"]].drop(columns=["has_geometry"])
    pub.to_file(web / "stations.geojson", driver="GeoJSON")
    # Full list including stations without geometry; the next build diffs against it.
    pd.DataFrame(stations.drop(columns="geometry")).to_csv(web / "stations.csv", index=False)
    shutil.copy(ROOT / "web" / "index.html", web / "index.html")
    (web / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    (out / "CHANGES.txt").write_text(f"Build {generated}\n" + "\n".join(changes) + "\n")
    print("\n".join(changes))
