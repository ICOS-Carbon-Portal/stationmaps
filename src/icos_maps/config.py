"""Static configuration: member countries, colours, sources."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "cache"
FONTS = ROOT / "assets" / "fonts"

SPARQL_URL = "https://meta.icos-cp.eu/sparql"
OCEAN_ZARR = "https://zarr.icos-cp.eu/icos-socat.zarr"
GISCO_URL = "https://gisco-services.ec.europa.eu/distribution/v2/countries/geojson/CNTR_RG_{res}M_2024_4326.geojson"
GISCO_CREDIT = "© EuroGeographics for the administrative boundaries"

# The 16 ICOS member countries (ISO 3166 alpha-2, as used by the Carbon Portal).
MEMBERS = {
    "BE": "Belgium",
    "CZ": "Czech Republic",
    "DK": "Denmark",
    "FI": "Finland",
    "FR": "France",
    "DE": "Germany",
    "GR": "Greece",
    "HU": "Hungary",
    "IE": "Ireland",
    "IT": "Italy",
    "NL": "The Netherlands",
    "NO": "Norway",
    "ES": "Spain",
    "SE": "Sweden",
    "CH": "Switzerland",
    "GB": "United Kingdom",
}

# Carbon Portal country codes that belong to a member's network (overseas territories etc.).
TERRITORIES = {
    "FR": ["FR", "GF", "RE", "GP", "MQ", "YT", "PF", "NC"],
    "DK": ["DK", "GL", "FO"],
    "NO": ["NO", "SJ"],
}

# Stations run by a member country other than the one they stand in (station ID -> member).
OPERATED_BY = {
    "ZA-Wgn": "FI",  # Welgegund, South Africa
    "CD-Ygb": "BE",  # Yangambi, DR Congo
    "RUN": "BE",     # La Réunion, French territory
}

# GISCO uses EU codes for a few countries.
ISO_TO_GISCO = {"GR": "EL", "GB": "UK"}

# Station classes that count as part of the ICOS network.
NETWORK_CLASSES = {"1", "2", "Associated"}

THEMES = ["atmosphere", "ecosystem", "ocean"]
THEME_LABEL = {
    "atmosphere": "Atmosphere Station",
    "ecosystem": "Ecosystem Station",
    "ocean": "Ocean Station",
    "multi": "Multi-domain Station",
}

# Colours sampled from the ICOS Handbook 2024 maps.
COLORS = {
    "atmosphere": "#E5007D",
    "ecosystem": "#AFCA0B",
    "ocean": "#00A6C8",
    "multi": "#5B3C92",
    "soop": "#0B3B7A",
    "focus_land": "#C6E2EE",
    "host_land": "#ECEFF2",  # country a station stands in when another member runs it
    "border": "#00A6C8",
    "other_land": "#FFFFFF",
    "locator_land": "#E3E3E3",
    "locator_focus": "#8C8C8C",
    "frame": "#00A6C8",
    "text": "#1A1A1A",
}

# Co-located stations closer than this (km) are a multi-domain station on the overview map.
MULTI_DOMAIN_KM = 2.0
# Ocean tracks: use cruises from the last N years (falls back to the most recent cruise).
TRACK_YEARS = 2
