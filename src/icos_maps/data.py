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
       (group_concat(distinct ?pi_name; separator="; ") as ?pi)
       (group_concat(distinct ?aff; separator="; ") as ?affiliation)
FROM <http://meta.icos-cp.eu/resources/stationentry/>
FROM <http://meta.icos-cp.eu/ontologies/stationentry/>
WHERE {
  ?uri cpst:hasCountry ?country ; cpst:hasLongName ?name ; cpst:hasStationClass ?cls0 ;
       cpst:hasShortName ?id ; a/rdfs:label ?theme_label .
  optional { ?uri cpst:hasLat ?lat ; cpst:hasLon ?lon }
  optional { ?uri cpst:hasSiteType ?site_type }
  optional { ?uri cpst:hasProductionCounterpart ?prod }
  optional {
    ?uri cpst:hasPi ?pi_r . ?pi_r cpst:hasFirstName ?pf ; cpst:hasLastName ?pl .
    optional { ?pi_r cpst:hasAffiliation ?aff }
    bind(concat(?pf, " ", ?pl) as ?pi_name)
  }
  bind(if(contains(?cls0, "Ass"), "Associated", ?cls0) as ?cls)
}
group by ?uri ?id ?name ?theme_label ?cls ?country ?lat ?lon ?site_type ?prod
"""

# Current PIs of production stations (memberships with the PI role that have not ended).
PI_QUERY = """
prefix cpmeta: <http://meta.icos-cp.eu/ontologies/cpmeta/>
select ?uri (group_concat(distinct ?pi_name; separator="; ") as ?pi) where {
  ?uri cpmeta:hasStationClass [] .
  ?memb cpmeta:atOrganization ?uri ; cpmeta:hasRole <http://meta.icos-cp.eu/resources/roles/PI> .
  ?person cpmeta:hasMembership ?memb ; cpmeta:hasFirstName ?fn ; cpmeta:hasLastName ?ln .
  filter not exists { ?memb cpmeta:hasEndTime ?end . filter(?end < now()) }
  bind(concat(?fn, " ", ?ln) as ?pi_name)
} group by ?uri
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


def labelling_entries(refresh: bool = False) -> pd.DataFrame:
    return _cached_query("labelling_entries.csv", ENTRIES_QUERY, refresh).drop_duplicates("uri")


def labelling_candidates(entries: pd.DataFrame) -> pd.DataFrame:
    """Labelling-application entries without a production station: stations not yet labelled."""
    df = entries[entries["prod"] == ""].drop(columns="prod").copy()
    df["theme"] = df.pop("theme_label").map(ENTRY_THEMES)
    df["host"] = df.pop("affiliation")
    df["labeled"] = ""
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
    pis = _cached_query("station_pis.csv", PI_QUERY, refresh).set_index("uri")["pi"]
    df["pi"] = df["uri"].map(pis).fillna("")
    entries = labelling_entries(refresh)
    # Where the station has no responsible organisation, use its labelling PI's affiliation.
    affiliation = entries[entries["prod"] != ""].set_index("prod")["affiliation"]
    df["host"] = df["host"].where(df["host"] != "", df["uri"].map(affiliation).fillna(""))
    df = pd.concat([df, labelling_candidates(entries)], ignore_index=True)
    for col in ("lat", "lon", "elevation"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["labeled"] = df["labeled"].str.slice(0, 10)
    df["status"] = df["labeled"].map(lambda d: "Labelled" if d else "Not yet labelled")
    # Ocean IDs look like "NO-SOOP-Nuka Arctica" (candidates sometimes only in the long name).
    df["platform"] = (df["id"] + " " + df["name"]).str.extract(r"\b(FOS|SOOP)\b")[0].fillna("")
    df = df.sort_values(["country", "name", "theme"]).reset_index(drop=True)
    geom = [Point(x, y) if pd.notna(x) and pd.notna(y) else None for x, y in zip(df["lon"], df["lat"])]
    return gpd.GeoDataFrame(df, geometry=geom, crs="EPSG:4326")
