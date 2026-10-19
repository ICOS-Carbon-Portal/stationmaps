"""Country boundaries from Eurostat GISCO, cached locally."""

from functools import cache

import geopandas as gpd
import requests

from .config import CACHE, GISCO_URL, ISO_TO_GISCO


@cache
def countries(res: str = "03") -> gpd.GeoDataFrame:
    """GISCO country polygons, EPSG:4326. res: '01', '03', '10', '20' or '60' (1:N million)."""
    path = CACHE / f"gisco_countries_{res}M.geojson"
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        resp = requests.get(GISCO_URL.format(res=res), timeout=300)
        resp.raise_for_status()
        path.write_bytes(resp.content)
    return gpd.read_file(path)[["CNTR_ID", "NAME_ENGL", "geometry"]]


def country_geom(iso: str, res: str = "03"):
    gdf = countries(res)
    return gdf.loc[gdf["CNTR_ID"] == ISO_TO_GISCO.get(iso, iso), "geometry"].union_all()
