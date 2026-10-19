"""Draw map panels with matplotlib.

Output is meant to be finished by an editor: SVG keeps text as <text> (svg.fonttype = none) and every
layer is its own named group (gid), PDF embeds Open Sans as TrueType so text stays editable.
"""

from pathlib import Path as FilePath

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager
from matplotlib.collections import PatchCollection
from matplotlib.lines import Line2D
from matplotlib.path import Path
from matplotlib.patches import PathPatch
from matplotlib.patches import Polygon as MplPolygon
from matplotlib.patches import Rectangle
from shapely.geometry import box

from .basemap import countries
from .config import COLORS, FONTS, GISCO_CREDIT, THEME_LABEL
from .layout import Panel, local_crs, territory_geom

MM = 1 / 25.4
PAGE_W_MM = 160  # map width follows the handbook text column; height follows the panel shape
MAX_MAP_H_MM = 210
FOOTER_MM = 20  # strip below the map for scale bar, north arrow and legend
MARGIN_MM = 3
LOCATOR_FRAC = 0.3  # locator inset width as a fraction of the map width
LOCATOR_MAX_KM = 3000  # panels wider than this get no locator inset
MARKER_PT = 9.0  # reference marker diameter; country maps scale it with the map size (MARKER_FRAC)
NUMBER_PT = 5.0  # station number size at the reference marker diameter
MARKER_FRAC = 0.0105  # marker diameter as a fraction of map width + height (about 9 pt on the France map)
EUROPE_LOCATOR = (-12, 34, 34, 71)  # lon/lat box for the locator inset of home panels


def setup_fonts():
    for f in FONTS.glob("*.ttf"):
        font_manager.fontManager.addfont(str(f))
    plt.rcParams.update({
        "font.family": "Open Sans",
        "svg.fonttype": "none",
        "pdf.fonttype": 42,
        "svg.hashsalt": "icos-maps",
        "path.simplify": True,
    })


def _extent_lonlat(crs, extent, n=40):
    """Densified panel boundary transformed to lon/lat bounds, for clipping the basemap."""
    x0, y0, x1, y1 = extent
    xs = np.concatenate([np.linspace(x0, x1, n), np.full(n, x1), np.linspace(x1, x0, n), np.full(n, x0)])
    ys = np.concatenate([np.full(n, y0), np.linspace(y0, y1, n), np.full(n, y1), np.linspace(y1, y0, n)])
    pts = gpd.GeoSeries(gpd.points_from_xy(xs, ys), crs=crs).to_crs("EPSG:4326")
    lon, lat = pts.x.to_numpy(), pts.y.to_numpy()
    ok = np.isfinite(lon) & np.isfinite(lat)
    if "+proj=robin" in crs.srs:
        return (-180, -90, 180, 90)
    if not ok.all():
        # Panel reaches beyond the projection's valid area: keep roughly the visible hemisphere.
        c = gpd.GeoSeries(gpd.points_from_xy([(x0 + x1) / 2], [(y0 + y1) / 2]), crs=crs).to_crs("EPSG:4326").iloc[0]
        return (max(c.x - 95, -180), max(c.y - 85, -90), min(c.x + 95, 180), min(c.y + 85, 90))
    return (max(lon[ok].min() - 2, -180), max(lat[ok].min() - 2, -90), min(lon[ok].max() + 2, 180), min(lat[ok].max() + 2, 90))


def _basemap(crs, extent, res):
    world = countries(res)
    clip = _extent_lonlat(crs, extent)
    if clip != (-180, -90, 180, 90):
        world = gpd.clip(world, box(*clip))
    world = world[~world.is_empty].to_crs(crs)
    return world[world.is_valid | True]


def _polygon_path(poly):
    rings = [poly.exterior, *poly.interiors]
    verts = np.concatenate([np.asarray(r.coords) for r in rings])
    codes = np.concatenate([[Path.MOVETO] + [Path.LINETO] * (len(r.coords) - 2) + [Path.CLOSEPOLY] for r in rings])
    return Path(verts, codes)


def _draw_polys(ax, geoms, gid, **kw):
    """Draw polygons (with holes) in one collection so they come out as one named SVG layer."""
    patches = [PathPatch(_polygon_path(part)) for g in geoms if g is not None
               for part in getattr(g, "geoms", [g]) if part.geom_type == "Polygon" and not part.is_empty]
    pc = PatchCollection(patches, **kw)
    pc.set_gid(gid)
    ax.add_collection(pc)
    return pc


def _nice(length_m):
    exp = 10 ** np.floor(np.log10(length_m))
    for m in (1, 2, 4, 10):  # quarter marks stay round numbers
        if m * exp >= length_m:
            return m * exp
    return 10 * exp


def new_map_figure(extent, width_mm=PAGE_W_MM, max_h_mm=MAX_MAP_H_MM, header_mm=0):
    """Figure whose height follows the extent's shape, with the map on top and a footer strip below."""
    aspect = (extent[3] - extent[1]) / (extent[2] - extent[0])
    map_w = width_mm - 2 * MARGIN_MM
    map_h = map_w * aspect
    if map_h > max_h_mm:
        map_h, map_w = max_h_mm, max_h_mm / aspect
    fig_h = map_h + FOOTER_MM + MARGIN_MM + header_mm
    fig = plt.figure(figsize=(width_mm * MM, fig_h * MM))
    ax = fig.add_axes([(width_mm - map_w) / 2 / width_mm, FOOTER_MM / fig_h, map_w / width_mm, map_h / fig_h])
    ax.set_gid("map")
    ax.set_xlim(extent[0], extent[2])
    ax.set_ylim(extent[1], extent[3])
    ax.set_aspect("equal", adjustable="box")
    ax.apply_aspect()
    ax.axis("off")
    return fig, ax


def _fy(fig, mm):
    """Vertical figure fraction for a distance in mm from the bottom."""
    return mm / (fig.get_size_inches()[1] / MM)


def marker_size(ax) -> float:
    """Marker diameter in points, proportional to the map's width + height, so stations look the same
    relative to the map on small and large panels."""
    pos = ax.get_position()
    fw, fh = ax.figure.get_size_inches()
    return MARKER_FRAC * (pos.width * fw + pos.height * fh) * 72


def _metres_per_point(ax, extent):
    bbox = ax.get_position()
    fw, fh = ax.figure.get_size_inches()
    w_pt = bbox.width * fw * 72
    h_pt = bbox.height * fh * 72
    return max((extent[2] - extent[0]) / w_pt, (extent[3] - extent[1]) / h_pt)


def _spread(xy: np.ndarray, threshold: float):
    """Move overlapping markers apart on a small circle around their common centre."""
    n = len(xy)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if np.hypot(*(xy[i] - xy[j])) < threshold:
                parent[find(j)] = find(i)
    out = xy.copy()
    for root in set(find(i) for i in range(n)):
        members = [i for i in range(n) if find(i) == root]
        if len(members) < 2:
            continue
        c = xy[members].mean(axis=0)
        r = threshold / (2 * np.sin(np.pi / len(members))) if len(members) > 2 else threshold / 2
        angles = np.arctan2(xy[members, 1] - c[1], xy[members, 0] - c[0])
        if np.allclose(xy[members], c):
            angles = np.zeros(len(members))
        order = np.argsort(angles + np.arange(len(members)) * 1e-9)
        for k, idx in enumerate(np.array(members)[order]):
            a = np.pi / 2 + 2 * np.pi * k / len(members)
            out[idx] = c + r * np.array([np.cos(a), np.sin(a)])
    return out


def _line_anchor(geom):
    """Where to put the number marker of a SOOP line: the point on the route closest to its middle."""
    c = box(*geom.bounds).centroid
    return geom.interpolate(geom.project(c))


def _scalebar(fig, ax, extent):
    m_per_pt = _metres_per_point(ax, extent)
    fw, fh = fig.get_size_inches()
    bar_pt = 0.30 * ax.get_position().width * fw * 72
    total = _nice(bar_pt * m_per_pt * 0.8)
    seg_pt = total / m_per_pt / 4
    sax = fig.add_axes([0.03, _fy(fig, 4), 0.6, _fy(fig, 9)])
    sax.set_gid("scale-bar")
    sax.set_xlim(0, sax.get_position().width * fw * 72)
    sax.set_ylim(0, 1)
    sax.axis("off")
    x0 = 22
    for k in range(4):
        sax.add_patch(Rectangle((x0 + k * seg_pt, 0.42), seg_pt, 0.14, facecolor="black" if k % 2 == 0 else "white",
                                edgecolor="black", linewidth=0.5))
    unit, div = ("km", 1000) if total >= 1000 else ("m", 1)
    for k in range(5):
        v = total / 4 * k / div
        sax.text(x0 + k * seg_pt, 0.12, f"{v:,.0f}".replace(",", " "), ha="center", va="bottom", fontsize=5.5)
    sax.text(x0 + 4 * seg_pt + 5, 0.49, unit.capitalize() if unit == "km" else unit, ha="left", va="center", fontsize=5.5)
    # North arrow (LAEA panels are north-up at their centre).
    sax.add_patch(MplPolygon([[6, 0.3], [11, 0.95], [16, 0.3], [11, 0.48]], closed=True, facecolor="black", edgecolor="none",
                             gid="north-arrow"))
    sax.text(11, 1.0, "N", ha="center", va="bottom", fontsize=5.5, fontweight="bold")


def _legend(fig, themes, has_lines):
    handles = [Line2D([], [], marker="o", linestyle="", markersize=5.5, markerfacecolor=COLORS[t], markeredgecolor="white",
                      markeredgewidth=0.4, label=THEME_LABEL[t]) for t in themes]
    if has_lines:
        handles.append(Line2D([], [], color=COLORS["soop"], linewidth=0.9, label="Ship of Opportunity (SOOP) Line"))
    leg = fig.legend(handles=handles, loc="lower right", bbox_to_anchor=(0.98, _fy(fig, 4)), frameon=False, fontsize=6,
                     handletextpad=0.4, labelspacing=0.35, borderaxespad=0)
    leg.set_gid("legend")


def _proj_kind(crs):
    return "robin" if "+proj=robin" in crs.srs else ""


def _locator_frame(panel: Panel):
    """Projection and bounds of the locator inset, or None when the panel needs no locator."""
    width = panel.extent[2] - panel.extent[0]
    if _proj_kind(panel.crs) == "robin" or width > LOCATOR_MAX_KM * 1000:
        return None
    if panel.kind == "home":
        lcrs = local_crs(11, 52)
        return lcrs, tuple(gpd.GeoSeries([box(*EUROPE_LOCATOR)], crs="EPSG:4326").to_crs(lcrs).total_bounds)
    cx = (panel.extent[0] + panel.extent[2]) / 2
    cy = (panel.extent[1] + panel.extent[3]) / 2
    c = gpd.GeoSeries(gpd.points_from_xy([cx], [cy]), crs=panel.crs).to_crs("EPSG:4326").iloc[0]
    half = max(2_500_000, 3 * max(width, panel.extent[3] - panel.extent[1]))
    return local_crs(c.x, c.y), (-half, -half * 0.8, half, half * 0.8)


def place_locator(extent, frame_bounds, land, xy):
    """Choose the map corner where the locator covers the least land and no stations.
    If every corner is occupied, widen the extent on one side to make room.
    Returns (extent, corner box in map units)."""
    loc_aspect = (frame_bounds[3] - frame_bounds[1]) / (frame_bounds[2] - frame_bounds[0])

    def corner_boxes(ext):
        x0, y0, x1, y1 = ext
        w = LOCATOR_FRAC * (x1 - x0)
        h = w * loc_aspect
        return {"ur": (x1 - w, y1 - h, x1, y1), "ul": (x0, y1 - h, x0 + w, y1),
                "lr": (x1 - w, y0, x1, y0 + h), "ll": (x0, y0, x0 + w, y0 + h)}

    def score(b):
        n = int(((xy[:, 0] > b[0]) & (xy[:, 0] < b[2]) & (xy[:, 1] > b[1]) & (xy[:, 1] < b[3])).sum()) if len(xy) else 0
        area = (b[2] - b[0]) * (b[3] - b[1])
        return n * 10 + land.intersection(box(*b)).area / area

    boxes = corner_boxes(extent)
    key = min(boxes, key=lambda k: score(boxes[k]))
    if score(boxes[key]) > 0.03:
        x0, y0, x1, y1 = extent
        grow = LOCATOR_FRAC * (x1 - x0) / (1 - LOCATOR_FRAC)
        side = "r" if key[1] == "r" else "l"
        extent = (x0, y0, x1 + grow, y1) if side == "r" else (x0 - grow, y0, x1, y1)
        boxes = corner_boxes(extent)
        key = min((k for k in boxes if k[1] == side), key=lambda k: score(boxes[k]))
    return extent, boxes[key]


def _locator(fig, ax, panel: Panel, cc: str, frame, corner_box):
    lcrs, ll = frame
    x0, y0, x1, y1 = panel.extent
    pos = ax.get_position()
    rect = [pos.x0 + (corner_box[0] - x0) / (x1 - x0) * pos.width, pos.y0 + (corner_box[1] - y0) / (y1 - y0) * pos.height,
            (corner_box[2] - corner_box[0]) / (x1 - x0) * pos.width, (corner_box[3] - corner_box[1]) / (y1 - y0) * pos.height]
    lax = fig.add_axes(rect)
    lax.set_gid("locator")
    world = _basemap(lcrs, ll, "20")
    focus = gpd.GeoSeries([territory_geom(cc)], crs="EPSG:4326").to_crs(lcrs)
    _draw_polys(lax, world.geometry, "locator-land", facecolor=COLORS["locator_land"], edgecolor="white", linewidth=0.25)
    _draw_polys(lax, focus, "locator-focus", facecolor=COLORS["locator_focus"], edgecolor="none")
    if panel.kind != "home":
        frame_poly = gpd.GeoSeries([box(*panel.extent)], crs=panel.crs).segmentize(10_000).to_crs(lcrs).iloc[0]
        _draw_polys(lax, [frame_poly], "locator-extent", facecolor="none", edgecolor=COLORS["frame"], linewidth=0.6)
    lax.set_xlim(ll[0], ll[2])
    lax.set_ylim(ll[1], ll[3])
    lax.set_xticks([])
    lax.set_yticks([])
    lax.set_facecolor("white")
    for sp in lax.spines.values():
        sp.set_edgecolor(COLORS["frame"])
        sp.set_linewidth(0.8)


def draw_stations(ax, stations: gpd.GeoDataFrame, extent, numbers: dict | None, colour_key="theme",
                  marker_pt=MARKER_PT, spread=True, line_width=0.7):
    """Lines first, then markers (spread apart where they overlap), then numbers on top."""
    lines = stations[stations.geometry.geom_type.isin(["LineString", "MultiLineString"])]
    if len(lines):
        for _, row in lines.iterrows():
            gpd.GeoSeries([row.geometry]).plot(ax=ax, color=COLORS["soop"], linewidth=line_width, zorder=3)
            ax.collections[-1].set_gid(f"soop-{row['id']}")
    anchors = [(_line_anchor(g) if g.geom_type != "Point" else g) for g in stations.geometry]
    xy = np.array([[p.x, p.y] for p in anchors]) if anchors else np.empty((0, 2))
    m_per_pt = _metres_per_point(ax, extent)
    moved = _spread(xy, marker_pt * 1.05 * m_per_pt) if len(xy) and spread else xy
    for (x, y), (mx, my) in zip(xy, moved):
        if np.hypot(x - mx, y - my) > 1:
            ax.plot([x, mx], [y, my], color="#555555", linewidth=0.4, zorder=4, gid="leader")
            ax.plot([x], [y], marker="o", markersize=1.6, color="#555555", zorder=4, gid="leader-origin")
    for key in stations[colour_key].unique():
        sel = (stations[colour_key] == key).to_numpy()
        sc = ax.scatter(moved[sel, 0], moved[sel, 1], s=marker_pt ** 2, c=COLORS[key], edgecolors="white", linewidths=0.5 * marker_pt / MARKER_PT, zorder=5)
        sc.set_gid(f"stations-{key}")
    if numbers:
        for (mx, my), sid in zip(moved, stations["id"]):
            t = ax.text(mx, my, str(numbers[sid]), ha="center", va="center", fontsize=NUMBER_PT * marker_pt / MARKER_PT, fontweight="bold", color="white", zorder=6)
            t.set_gid(f"number-{sid}")
    return moved


def render_panel(panel: Panel, cc: str, stations: gpd.GeoDataFrame, numbers: dict, out_base: FilePath, formats, res="03",
                 dpi=300, marker_scale=1.0):
    st = stations[stations["id"].isin(panel.station_ids)].to_crs(panel.crs)
    focus = gpd.GeoSeries([territory_geom(cc)], crs="EPSG:4326")
    focus = gpd.clip(focus, box(*_extent_lonlat(panel.crs, panel.extent))).to_crs(panel.crs)

    frame = _locator_frame(panel)
    if frame:
        anchors = np.array([[p.x, p.y] for p in (_line_anchor(g) if g.geom_type != "Point" else g for g in st.geometry)])
        panel.extent, corner_box = place_locator(panel.extent, frame[1], focus.union_all(), anchors.reshape(-1, 2))

    fig, ax = new_map_figure(panel.extent)
    world = _basemap(panel.crs, panel.extent, res if panel.kind != "ocean" else "10")
    _draw_polys(ax, world.geometry, "other-countries", facecolor=COLORS["other_land"], edgecolor=COLORS["border"], linewidth=0.4, zorder=1)
    _draw_polys(ax, focus, "focus-country", facecolor=COLORS["focus_land"], edgecolor=COLORS["border"], linewidth=0.6, zorder=2)
    marker_pt = marker_size(ax) * marker_scale
    moved = draw_stations(ax, st, panel.extent, numbers, marker_pt=marker_pt)
    hotspots = marker_positions(fig, ax, st["id"], moved, marker_pt)
    _scalebar(fig, ax, panel.extent)
    _legend(fig, [t for t in ("ocean", "atmosphere", "ecosystem") if (st["theme"] == t).any()],
            st.geometry.geom_type.str.contains("Line").any())
    if frame:
        _locator(fig, ax, panel, cc, frame, corner_box)
    fig.text(0.98, _fy(fig, 1), GISCO_CREDIT, ha="right", va="bottom", fontsize=3.5, color="#777777", gid="credit")
    save(fig, out_base, formats, dpi)
    return hotspots


def marker_positions(fig, ax, ids, xy, marker_pt):
    """Marker centres as fractions of the image (origin top-left) and the marker radius as a fraction
    of the image width, so the website can put clickable spots on top of the PNG."""
    w, h = fig.get_size_inches() * fig.dpi
    disp = ax.transData.transform(xy) if len(xy) else np.empty((0, 2))
    return {"r": round(marker_pt / 2 / 72 / fig.get_size_inches()[0], 5),
            "points": [{"id": i, "x": round(float(x / w), 5), "y": round(float(1 - y / h), 5)} for i, (x, y) in zip(ids, disp)]}


def save(fig, out_base: FilePath, formats, dpi=300):
    out_base.parent.mkdir(parents=True, exist_ok=True)
    for fmt in formats:
        kw = {"metadata": {"Date": None}} if fmt == "svg" else {}
        if fmt == "pdf":
            kw = {"metadata": {"CreationDate": None}}
        fig.savefig(out_base.with_suffix(f".{fmt}"), dpi=dpi if fmt == "png" else None, facecolor="white", **kw)
    plt.close(fig)
