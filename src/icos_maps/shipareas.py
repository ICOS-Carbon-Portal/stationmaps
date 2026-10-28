"""Ship (SOOP) tracks as shaded areas: "area covered by SOOP line".

Each ship's tracks are marked on a coarse grid, widened into a band, merged where bands come close
(dilate, then close the gaps), and traced back into a polygon. Working on a grid keeps this fast for
ships that sail the same route hundreds of times or survey in grids: merging that many overlapping
vector buffers would take minutes.
"""

import geopandas as gpd
import numpy as np
from rasterio import features
from rasterio.transform import from_origin
from shapely.geometry import Polygon, box, shape
from shapely.ops import unary_union

from .layout import _crs_for

MAX_LAT = 85.0  # tracks further north are dropped, so no area wraps around the pole
FRONT_PAGE_BAND_M = 25_000  # band half-width for the front-page maps


def _grow(mask: np.ndarray, k: int) -> np.ndarray:
    """Dilation by a disc of radius k cells: OR of the mask shifted to every offset within the disc."""
    padded = np.pad(mask, k)
    out = np.zeros_like(mask)
    h, w = mask.shape
    for dy in range(-k, k + 1):
        span = int((k * k - dy * dy) ** 0.5)
        for dx in range(-span, span + 1):
            out |= padded[k + dy: k + dy + h, k + dx: k + dx + w]
    return out


def track_area(track, half_width: float):
    """Area covered by a (projected, metres) track: a band of `half_width` with nearby bands merged."""
    if track.is_empty:
        return track
    cell = half_width / 4
    pad = 4 * half_width
    x0, y0, x1, y1 = track.bounds
    x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
    width, height = int((x1 - x0) / cell) + 1, int((y1 - y0) / cell) + 1
    transform = from_origin(x0, y1, cell, cell)
    mask = features.rasterize([(track, 1)], out_shape=(height, width), transform=transform, all_touched=True).astype(bool)
    k = max(1, round(half_width / cell))
    mask = _grow(mask, k)
    mask = ~_grow(~_grow(mask, 2 * k), 2 * k)  # close gaps between nearby bands
    polygons = [shape(s) for s, v in features.shapes(mask.astype(np.uint8), mask=mask, transform=transform) if v]
    # Remove the grid staircase (simplify by about a cell), then smooth the outline into curves.
    return _smooth(unary_union(polygons).simplify(cell * 1.2))


def _chaikin(coords, iterations=4):
    """Chaikin corner cutting on a closed ring: each pass replaces every corner by two points at 1/4
    and 3/4 along its edges, converging to a smooth curve inside the original outline."""
    pts = np.asarray(coords)[:-1]
    for _ in range(iterations):
        nxt = np.roll(pts, -1, axis=0)
        pts = np.column_stack([0.75 * pts + 0.25 * nxt, 0.25 * pts + 0.75 * nxt]).reshape(-1, 2)
    return np.vstack([pts, pts[:1]])


def _smooth(geom):
    parts = []
    for poly in getattr(geom, "geoms", [geom]):
        if poly.geom_type != "Polygon" or poly.is_empty:
            continue
        holes = [_chaikin(r.coords) for r in poly.interiors if len(r.coords) > 3]
        parts.append(Polygon(_chaikin(poly.exterior.coords), holes).buffer(0))
    return unary_union(parts)


def clip_north(track):
    return track.intersection(box(-180, -90, 180, MAX_LAT))


def areas_in_crs(lines: gpd.GeoDataFrame, half_width: float) -> dict:
    """{station id: area} for tracks already in a projected CRS (a map panel's)."""
    return {sid: track_area(g, half_width) for sid, g in zip(lines["id"], lines.geometry)}


def areas_lonlat(lines: gpd.GeoDataFrame, half_width: float = FRONT_PAGE_BAND_M) -> gpd.GeoDataFrame:
    """Areas for tracks in EPSG:4326, each computed in a projection around its own track and
    returned in EPSG:4326."""
    rows = []
    for _, row in lines.iterrows():
        track = clip_north(row.geometry)
        if track.is_empty:
            continue
        crs = _crs_for([track])
        projected = gpd.GeoSeries([track], crs="EPSG:4326").to_crs(crs).iloc[0]
        area = gpd.GeoSeries([track_area(projected, half_width)], crs=crs).to_crs("EPSG:4326").iloc[0]
        rows.append({"id": row["id"], "geometry": area})
    return gpd.GeoDataFrame(rows, crs="EPSG:4326")
