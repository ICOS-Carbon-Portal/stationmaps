"""Ocean station geometry (SOOP tracks, FOS positions) from the ICOS ocean Zarr store."""

import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr
from shapely.geometry import LineString, MultiLineString, Point

from .config import CACHE, OCEAN_ZARR, TRACK_YEARS

MAX_POINTS_PER_CRUISE = 400
GAP_DEG = 3.0  # break a track where consecutive points jump further than this


def _segments(lon: np.ndarray, lat: np.ndarray) -> list[LineString]:
    ok = np.isfinite(lon) & np.isfinite(lat) & ~((lon == 0) & (lat == 0))  # (0, 0) is a fill value, not a position
    lon, lat = lon[ok], lat[ok]
    if len(lon) < 2:
        return []
    step = max(1, len(lon) // MAX_POINTS_PER_CRUISE)
    lon, lat = lon[::step], lat[::step]
    breaks = np.where((np.abs(np.diff(lon)) > GAP_DEG) | (np.abs(np.diff(lat)) > GAP_DEG))[0] + 1
    return [LineString(np.column_stack(p)) for p in zip(np.split(lon, breaks), np.split(lat, breaks)) if len(p[0]) > 1]


def fetch_ocean_geometry(refresh: bool = False) -> gpd.GeoDataFrame:
    """One row per ocean station in the Zarr store: station_uri, kind (FOS/SOOP), geometry."""
    cache = CACHE / "ocean_geometry.geojson"
    if cache.exists() and not refresh:
        return gpd.read_file(cache)

    ds = xr.open_zarr(OCEAN_ZARR, group="_obs", consolidated=True)
    station_uri = ds["station_uri"].values
    station_id = ds["station"].values
    cruise_station = ds["station_idx"].values
    starts = ds["obs_start"].values.astype(int)
    counts = ds["obs_count"].values.astype(int)
    fixed = ds["fixed"].values
    t_end = pd.to_datetime(ds["time_end"].values)
    lat = ds["latitude"].values
    lon = ds["longitude"].values
    cutoff = t_end.max() - pd.DateOffset(years=TRACK_YEARS)

    rows = []
    for i, uri in enumerate(station_uri):
        cruises = np.where(cruise_station == i)[0]
        if len(cruises) == 0:
            continue
        sl = [slice(starts[c], starts[c] + counts[c]) for c in cruises]
        if fixed[cruises].all():
            geom = Point(np.nanmedian(np.concatenate([lon[s] for s in sl])), np.nanmedian(np.concatenate([lat[s] for s in sl])))
            kind = "FOS"
        else:
            recent = [c for c in cruises if t_end[c] >= cutoff] or [cruises[np.argmax(t_end[cruises])]]
            lines = [seg for c in recent for seg in _segments(lon[starts[c]:starts[c] + counts[c]], lat[starts[c]:starts[c] + counts[c]])]
            geom = MultiLineString(lines).simplify(0.02)
            kind = "SOOP"
        rows.append({"station_uri": str(uri), "zarr_id": str(station_id[i]), "kind": kind, "n_cruises": len(cruises), "geometry": geom})

    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    CACHE.mkdir(parents=True, exist_ok=True)
    gdf.to_file(cache, driver="GeoJSON")
    return gdf


def attach_ocean_geometry(stations: gpd.GeoDataFrame, ocean: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Give ocean stations geometry: SOOP lines get their Zarr tracks, FOS keep the Carbon Portal
    position and fall back to the median Zarr position."""
    stations = stations.copy()
    geom_by_uri = dict(zip(ocean["station_uri"], ocean.geometry))
    for idx, row in stations[stations["theme"] == "ocean"].iterrows():
        geom = geom_by_uri.get(row["uri"])
        if geom is None:
            continue
        if row["platform"] == "SOOP":
            stations.at[idx, "geometry"] = geom
        elif row.geometry is None:
            stations.at[idx, "geometry"] = geom if geom.geom_type == "Point" else geom.centroid
    stations["has_geometry"] = stations.geometry.notna() & ~stations.geometry.is_empty
    return stations
