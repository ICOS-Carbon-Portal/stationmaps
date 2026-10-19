"""The network overview map (handbook page 5): Europe plus a world inset for SOOP lines and remote stations."""

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
from pyproj import CRS
from shapely.geometry import box

from .config import COLORS, GISCO_CREDIT, MULTI_DOMAIN_KM
from .layout import local_crs
from .render import _basemap, _draw_polys, _fy, _legend, _scalebar, draw_stations, new_map_figure, save

EUROPE_CRS = CRS.from_epsg(3035)
EUROPE_BOX = (-30, 27, 42, 82)  # lon/lat window treated as "Europe" for the main map


def merge_multi_domain(stations: gpd.GeoDataFrame, crs) -> gpd.GeoDataFrame:
    """Point stations of different domains within MULTI_DOMAIN_KM become one multi-domain marker."""
    pts = stations[stations.geometry.geom_type == "Point"].to_crs(crs)
    lines = stations[stations.geometry.geom_type != "Point"].to_crs(crs)
    pts = pts.assign(colour=pts["theme"])
    used, rows = set(), []
    for i, row in pts.iterrows():
        if i in used:
            continue
        near = pts[pts.geometry.distance(row.geometry) < MULTI_DOMAIN_KM * 1000]
        used |= set(near.index)
        r = row.copy()
        if near["theme"].nunique() > 1:
            r["colour"] = "multi"
            r["id"] = "+".join(near["id"])
        rows.append(r)
    merged = gpd.GeoDataFrame(rows, crs=crs)
    return gpd.GeoDataFrame([*merged.to_dict("records"), *lines.assign(colour="ocean").to_dict("records")], crs=crs)


def render_overview(stations: gpd.GeoDataFrame, out_base, formats):
    mapped = stations[stations["has_geometry"]]
    in_eu = mapped.geometry.intersects(box(*EUROPE_BOX)) & (mapped.geometry.geom_type == "Point")
    eu_bounds = mapped[in_eu].to_crs(EUROPE_CRS).total_bounds
    pad = 150_000
    extent = (eu_bounds[0] - pad, eu_bounds[1] - pad, eu_bounds[2] + pad, eu_bounds[3] + pad)

    fig, ax = new_map_figure(extent, width_mm=240, max_h_mm=230, header_mm=14)
    world = _basemap(EUROPE_CRS, extent, "10")
    _draw_polys(ax, world.geometry, "countries", facecolor="white", edgecolor=COLORS["border"], linewidth=0.35, zorder=1)
    members = world[world["CNTR_ID"].isin(["BE", "CZ", "DK", "FI", "FR", "DE", "EL", "HU", "IE", "IT", "NL", "NO", "ES", "SE", "CH", "UK"])]
    _draw_polys(ax, members.geometry, "member-countries", facecolor=COLORS["focus_land"], edgecolor=COLORS["border"], linewidth=0.45, zorder=2)

    eu = merge_multi_domain(mapped[in_eu | (mapped.geometry.geom_type != "Point")], EUROPE_CRS)
    eu = eu[eu.geometry.intersects(box(*extent))]
    eu["geometry"] = eu.geometry.clip_by_rect(*extent)  # plain clip; intersection() would node self-crossing tracks
    draw_stations(ax, eu, extent, numbers=None, colour_key="colour", marker_pt=5, spread=False, line_width=0.35)

    # World inset: all SOOP lines plus stations outside the European window.
    wcrs = local_crs(0, 0, 360, 180)
    pos = ax.get_position()
    wax = fig.add_axes([pos.x0, pos.y0, 0.36 * pos.width, 0.36 * pos.width * 0.52 * fig.get_size_inches()[0] / fig.get_size_inches()[1]])
    wax.set_gid("world-inset")
    wext = (-15_000_000, -7_500_000, 15_000_000, 8_200_000)
    wworld = _basemap(wcrs, wext, "60")
    _draw_polys(wax, wworld.geometry, "world-land", facecolor=COLORS["locator_land"], edgecolor="white", linewidth=0.2)
    frame = gpd.GeoSeries([box(*extent)], crs=EUROPE_CRS).segmentize(50_000).to_crs(wcrs)
    _draw_polys(wax, frame, "europe-extent", facecolor="none", edgecolor=COLORS["frame"], linewidth=0.6)
    far = merge_multi_domain(mapped[~in_eu], wcrs)
    wax.set_xlim(wext[0], wext[2])
    wax.set_ylim(wext[1], wext[3])
    wax.set_aspect("equal", adjustable="box")
    wax.apply_aspect()
    for _, row in far[far.geometry.geom_type != "Point"].iterrows():
        gpd.GeoSeries([row.geometry]).plot(ax=wax, color=COLORS["soop"], linewidth=0.35, zorder=3)
        wax.collections[-1].set_gid(f"soop-{row['id']}")
    for key, grp in far[far.geometry.geom_type == "Point"].groupby("colour"):
        wax.scatter(grp.geometry.x, grp.geometry.y, s=12, c=COLORS[key], edgecolors="white", linewidths=0.3, zorder=5, gid=f"inset-stations-{key}")
    wax.set_xlabel("")
    wax.set_ylabel("")
    wax.set_xticks([])
    wax.set_yticks([])
    wax.set_facecolor("white")
    for s in wax.spines.values():
        s.set_edgecolor(COLORS["frame"])
        s.set_linewidth(0.8)

    fig.text(0.03, 1 - _fy(fig, 3), "ICOS Station Network", fontsize=14, fontweight="bold", color=COLORS["ocean"], va="top", gid="title")
    _scalebar(fig, ax, extent)
    _legend(fig, ["ocean", "atmosphere", "ecosystem", "multi"], True)
    fig.text(0.98, _fy(fig, 1), GISCO_CREDIT, ha="right", va="bottom", fontsize=3.5, color="#777777", gid="credit")
    save(fig, out_base, formats)
