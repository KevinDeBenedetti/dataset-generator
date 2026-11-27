"""API Adresse (Base Adresse Nationale), now served by the IGN's Géoplateforme
(data.geopf.fr/geocodage): search and reverse geocoding. No key; 50 calls a
second per address; at most 50 results an answer, no paging. The BAN is under
the Licence Ouverte 2.0.

For many addresses at once, the API's CSV geocoding is a POST of a file, which
no connector sends: take the BAN's own files instead — one CSV per
département at adresse.data.gouv.fr/data/ban/adresses/latest/csv/ — with the
File at a URL connector (docs/sources.md).
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field

from server.connectors.presets import Preset

BASE = "https://data.geopf.fr/geocodage"
PRODUCER = "Base Adresse Nationale (IGN, Géoplateforme)"
LICENCE = "Licence Ouverte 2.0"
DOCS = (
    "https://geoservices.ign.fr/documentation/services/services-geoplateforme/geocodage"
)


class SearchForm(BaseModel):
    q: str = Field(
        ..., min_length=3, max_length=200, description="The address to look for"
    )
    citycode: Optional[str] = Field(
        None, pattern=r"^[0-9AB]{5}$", description="Only in this commune (INSEE code)"
    )
    type: Optional[Literal["housenumber", "street", "locality", "municipality"]] = None
    limit: int = Field(20, ge=1, le=50)


class ReverseForm(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    limit: int = Field(10, ge=1, le=50)


def _search(form: SearchForm) -> dict:
    params = {"q": form.q, "limit": str(form.limit)}
    if form.citycode:
        params["citycode"] = form.citycode
    if form.type:
        params["type"] = form.type
    return {
        "url": f"{BASE}/search",
        "params": params,
        "records_path": "$.features",
        "pagination": {"type": "none"},
    }


def _reverse(form: ReverseForm) -> dict:
    return {
        "url": f"{BASE}/reverse",
        "params": {
            "lat": str(form.lat),
            "lon": str(form.lon),
            "limit": str(form.limit),
        },
        "records_path": "$.features",
        "pagination": {"type": "none"},
    }


PRESETS = [
    Preset(
        id="adresse-search",
        title="API Adresse — search",
        description="The addresses matching a text (50 at most), with their codes and coordinates",
        producer=PRODUCER,
        licence=LICENCE,
        docs_url=DOCS,
        rate_limit_per_s=10,
        form=SearchForm,
        build=_search,
        name=lambda f: f"Adresses « {f.q[:60]} »",
    ),
    Preset(
        id="adresse-reverse",
        title="API Adresse — reverse geocoding",
        description="The addresses nearest a point",
        producer=PRODUCER,
        licence=LICENCE,
        docs_url=DOCS,
        rate_limit_per_s=10,
        form=ReverseForm,
        build=_reverse,
        name=lambda f: f"Adresses près de {f.lat:.4f}, {f.lon:.4f}",
    ),
]
