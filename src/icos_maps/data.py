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


# Station entries of the labelling application, including candidates that have no production
# station yet. Based on the Carbon Portal's labelling overview query.
ENTRIES_QUERY = """
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX cpst: <http://meta.icos-cp.eu/ontologies/stationentry/>
SELECT ?uri ?id ?name ?theme_label ?cls ?country ?lat ?lon ?site_type ?prod
FROM <http://meta.icos-cp.eu/resources/stationentry/>
FROM <http://meta.icos-cp.eu/ontologies/stationentry/>
WHERE {
  ?uri cpst:hasCountry ?country ; cpst:hasLongName ?name ; cpst:hasStationClass ?cls0 ;
       cpst:hasShortName ?id ; a/rdfs:label ?theme_label .
  optional { ?uri cpst:hasLat ?lat ; cpst:hasLon ?lon }
  optional { ?uri cpst:hasSiteType ?site_type }
  optional { ?uri cpst:hasProductionCounterpart ?prod }
  bind(if(contains(?cls0, "Ass"), "Associated", ?cls0) as ?cls)
}
"""
ENTRY_THEMES = {"Atmospheric Station": "atmosphere", "Ecosystem Station": "ecosystem", "Ocean Station": "ocean"}


def sparql_csv(query: str) -> pd.DataFrame:
    resp = requests.post(SPARQL_URL, data={"query": query}, headers={"Accept": "text/csv"}, timeout=120)
    resp.raise_for_status()
    return pd.read_csv(io.StringIO(resp.text), dtype=str, keep_default_na=False)


def _cached_query(name: str, query: str, refresh: bool) -> pd.DataFrame:
    cache = CACHE / name
    if refresh or not cache.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        sparql_csv(query).to_csv(cache, index=False)
    return pd.read_csv(cache, dtype=str, keep_default_na=False)


def labelling_candidates(refresh: bool = False) -> pd.DataFrame:
    """Labelling-application entries without a production station: stations not yet labelled."""
    df = _cached_query("labelling_entries.csv", ENTRIES_QUERY, refresh).drop_duplicates("uri")
    df = df[df["prod"] == ""].drop(columns="prod")
    df["theme"] = df.pop("theme_label").map(ENTRY_THEMES)
    df["labeled"] = ""
    df["host"] = ""
    df["elevation"] = ""
    df["source"] = "labelling"
    # Their entry URIs are not public pages; the table shows their names without a link.
    df["link"] = ""
    return df


def fetch_stations(refresh: bool = False) -> gpd.GeoDataFrame:
    """All ICOS network stations as points (ocean lines have no geometry yet): production stations of
    class 1, 2 or Associated plus labelling candidates that have no production station yet."""
    df = _cached_query("stations.csv", STATIONS_QUERY, refresh)
    df = df[df["cls"].isin(NETWORK_CLASSES)].copy()
    df["source"] = "production"
    df["link"] = df["uri"]
    df = pd.concat([df, labelling_candidates(refresh)], ignore_index=True)
    for col in ("lat", "lon", "elevation"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["labeled"] = df["labeled"].str.slice(0, 10)
    df["status"] = df["labeled"].map(lambda d: "Labelled" if d else "Not yet labelled")
    # Ocean IDs look like "NO-SOOP-Nuka Arctica" (candidates sometimes only in the long name).
    df["platform"] = (df["id"] + " " + df["name"]).str.extract(r"\b(FOS|SOOP)\b")[0].fillna("")
    df = df.sort_values(["country", "name", "theme"]).reset_index(drop=True)
    geom = [Point(x, y) if pd.notna(x) and pd.notna(y) else None for x, y in zip(df["lon"], df["lat"])]
    return gpd.GeoDataFrame(df, geometry=geom, crs="EPSG:4326")
