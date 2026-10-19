"""Station metadata from the ICOS Carbon Portal SPARQL endpoint."""

import io

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import Point

from .config import CACHE, NETWORK_CLASSES, SPARQL_URL

STATIONS_QUERY = """
prefix cpmeta: <http://meta.icos-cp.eu/ontologies/cpmeta/>
prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>
select ?uri ?id ?name ?country ?theme ?cls ?lat ?lon ?elevation ?labeled
       (group_concat(distinct ?orgName; separator="; ") as ?host)
       (sample(?eco) as ?site_type)
where {
  values (?type ?theme) {(cpmeta:AS "atmosphere") (cpmeta:ES "ecosystem") (cpmeta:OS "ocean")}
  ?uri a ?type ; cpmeta:hasStationId ?id ; cpmeta:hasName ?name ;
       cpmeta:countryCode ?country ; cpmeta:hasStationClass ?cls .
  optional { ?uri cpmeta:hasLatitude ?lat ; cpmeta:hasLongitude ?lon }
  optional { ?uri cpmeta:hasElevation ?elevation }
  optional { ?uri cpmeta:hasLabelingDate ?labeled }
  optional { ?uri cpmeta:hasResponsibleOrganization/cpmeta:hasName ?orgName }
  optional { ?uri cpmeta:hasEcosystemType/rdfs:label ?eco }
}
group by ?uri ?id ?name ?country ?theme ?cls ?lat ?lon ?elevation ?labeled
"""


def sparql_csv(query: str) -> pd.DataFrame:
    resp = requests.post(SPARQL_URL, data={"query": query}, headers={"Accept": "text/csv"}, timeout=120)
    resp.raise_for_status()
    return pd.read_csv(io.StringIO(resp.text), dtype=str, keep_default_na=False)


def fetch_stations(refresh: bool = False) -> gpd.GeoDataFrame:
    """All ICOS network stations (class 1, 2, Associated) as points; ocean lines have empty geometry."""
    cache = CACHE / "stations.csv"
    if refresh or not cache.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        sparql_csv(STATIONS_QUERY).to_csv(cache, index=False)
    df = pd.read_csv(cache, dtype=str, keep_default_na=False)
    df = df[df["cls"].isin(NETWORK_CLASSES)].copy()
    for col in ("lat", "lon", "elevation"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["labeled"] = df["labeled"].str.slice(0, 10)
    # Ocean IDs look like "NO-SOOP-Nuka Arctica"; atmosphere IDs like "JFJ"; ecosystem like "CH-Dav".
    df["platform"] = df["id"].str.extract(r"^[A-Z]{2}-(FOS|SOOP)-")[0].fillna("")
    df = df.sort_values(["country", "name", "theme"]).reset_index(drop=True)
    geom = [Point(x, y) if pd.notna(x) and pd.notna(y) else None for x, y in zip(df["lon"], df["lat"])]
    return gpd.GeoDataFrame(df, geometry=geom, crs="EPSG:4326")
