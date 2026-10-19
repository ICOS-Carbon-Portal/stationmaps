"""Decide which map panels a country needs and their projection/extent.

Panel a: the home (European) territory with its point stations.
Further panels: remote point stations (overseas territories, Svalbard, Canaries, Greenland ...)
and one ocean panel when the country has SOOP lines or fixed ocean stations off the home map.
"""

from dataclasses import dataclass, field

import geopandas as gpd
import numpy as np
from pyproj import CRS
from shapely.geometry import box
from shapely.ops import unary_union

from .basemap import country_geom
from .config import TERRITORIES

ARCHIPELAGO_KM = 300  # land parts this close to the home landmass belong to the home panel
REMOTE_KM = 100  # point stations further than this outside the home panel get their own panel
CLUSTER_KM = 1500  # remote stations closer than this share a panel
MIN_PANEL_KM = 150


@dataclass
class Panel:
    key: str  # "a", "b", ...
    kind: str  # "home", "remote", "ocean", "overview"
    crs: CRS
    extent: tuple[float, float, float, float]  # projected xmin, ymin, xmax, ymax
    station_ids: list[str] = field(default_factory=list)
    title: str = ""


def local_crs(lon: float, lat: float, span_lon: float = 0, span_lat: float = 0, lat_max: float = 0) -> CRS:
    if lat_max > 75 and span_lon > 90:  # Arctic routes: polar view centred on Europe's meridian
        return CRS.from_proj4("+proj=laea +lat_0=90 +lon_0=10 +datum=WGS84 +units=m +no_defs")
    if span_lat > 90 or span_lon > 150:
        # lon_0=0 keeps the seam on the antimeridian, where the GISCO polygons are already split.
        return CRS.from_proj4("+proj=robin +lon_0=0 +datum=WGS84 +units=m +no_defs")
    return CRS.from_proj4(f"+proj=laea +lat_0={lat:.1f} +lon_0={lon:.1f} +datum=WGS84 +units=m +no_defs")


def territory_geom(cc: str):
    return unary_union([g for code in TERRITORIES.get(cc, [cc]) if (g := country_geom(code)) is not None and not g.is_empty])


def _pad(bounds, frac=0.08, min_m=MIN_PANEL_KM * 1000):
    x0, y0, x1, y1 = bounds
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    w, h = max(x1 - x0, min_m), max(y1 - y0, min_m)
    w, h = w * (1 + 2 * frac), h * (1 + 2 * frac)
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def _crs_for(geoms_4326) -> CRS:
    b = gpd.GeoSeries(geoms_4326, crs="EPSG:4326").total_bounds
    return local_crs((b[0] + b[2]) / 2, (b[1] + b[3]) / 2, b[2] - b[0], b[3] - b[1], b[3])


def home_landmass(cc: str):
    """Largest land part plus every part within ARCHIPELAGO_KM of it (transitively), in EPSG:4326."""
    parts = sorted(gpd.GeoSeries([territory_geom(cc)], crs="EPSG:4326").explode().tolist(), key=lambda g: g.area, reverse=True)
    c = parts[0].centroid
    crs = local_crs(c.x, c.y)
    proj = gpd.GeoSeries(parts, crs="EPSG:4326").to_crs(crs)
    included = {0}
    grown = True
    while grown:
        core = unary_union([proj.iloc[i] for i in included])
        new = {i for i in range(len(parts)) if i not in included and proj.iloc[i].distance(core) < ARCHIPELAGO_KM * 1000}
        grown = bool(new)
        included |= new
    return unary_union([parts[i] for i in included])


def _clusters(points: gpd.GeoSeries, km: float) -> list[list[int]]:
    xy = np.column_stack([points.x, points.y])
    labels = list(range(len(xy)))
    for i in range(len(xy)):
        for j in range(i + 1, len(xy)):
            if np.hypot(*(xy[i] - xy[j])) < km * 1000:
                old, new = labels[j], labels[i]
                labels = [new if lab == old else lab for lab in labels]
    return [[i for i, lab in enumerate(labels) if lab == g] for g in dict.fromkeys(labels)]


def plan_country(cc: str, stations: gpd.GeoDataFrame) -> list[Panel]:
    """stations: this country's mapped stations (EPSG:4326)."""
    home = home_landmass(cc)
    c = home.centroid
    crs = local_crs(c.x, c.y)
    home_p = gpd.GeoSeries([home], crs="EPSG:4326").to_crs(crs).iloc[0]
    proj = stations.to_crs(crs)
    is_line = stations["platform"] == "SOOP"
    points = proj[~is_line]
    near = points.geometry.distance(box(*home_p.bounds)) < REMOTE_KM * 1000
    home_pts = points[near]
    ocean_home = home_pts["theme"] == "ocean"
    # Fixed ocean stations far offshore (e.g. PAP) go to the ocean panel rather than stretching the home map.
    offshore = ocean_home & (home_pts.geometry.distance(home_p) > ARCHIPELAGO_KM * 1000)
    home_pts = home_pts[~offshore]

    bounds = unary_union([home_p, *home_pts.geometry]).bounds
    panels = [Panel("a", "home", crs, _pad(bounds), home_pts["id"].tolist())]

    far = points[~near]
    ocean_ids = set(stations.loc[is_line, "id"]) | set(far.loc[far["theme"] == "ocean", "id"]) | set(points.loc[offshore[offshore].index, "id"])
    remote = stations.loc[far[far["theme"] != "ocean"].index]
    if len(remote):
        for group in _clusters(remote.to_crs(crs).geometry, CLUSTER_KM):
            grp = remote.iloc[group]
            # Stations can stand in another country than the member running them (config.OPERATED_BY):
            # frame the land they stand on as well.
            land = unary_union([territory_geom(cc), *(country_geom(c) for c in grp["country"].unique())])
            buf = gpd.GeoSeries(grp.geometry, crs="EPSG:4326").to_crs(crs).buffer(50_000).to_crs("EPSG:4326").union_all()
            land_parts = [p for p in gpd.GeoSeries([land], crs="EPSG:4326").explode() if p.intersects(buf)]
            pcrs = _crs_for(list(grp.geometry) + land_parts)
            geoms = gpd.GeoSeries(list(grp.geometry) + land_parts, crs="EPSG:4326").to_crs(pcrs)
            panels.append(Panel(chr(ord("a") + len(panels)), "remote", pcrs, _pad(geoms.total_bounds), grp["id"].tolist()))

    if ocean_ids:
        ocean = stations[stations["id"].isin(ocean_ids)]
        pcrs = _crs_for(list(ocean.geometry) + [home])
        geoms = gpd.GeoSeries(list(ocean.geometry) + [home], crs="EPSG:4326").to_crs(pcrs)
        panels.append(Panel(chr(ord("a") + len(panels)), "ocean", pcrs, _pad(geoms.total_bounds, 0.05), ocean["id"].tolist()))
    return panels
