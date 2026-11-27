"""Géo API (API Découpage administratif): communes, départements and regions
with their codes and population. No key. The data is the INSEE's Code
officiel géographique and legal populations, under the Licence Ouverte
(datagouv/decoupage-administratif); 50 calls a second per address. One
answer holds the whole list: no paging."""

from typing import Literal, Optional

from pydantic import BaseModel, Field

from server.connectors.presets import Preset

BASE = "https://geo.api.gouv.fr"
PRODUCER = "Géo API (DINUM), from INSEE's Code officiel géographique"
LICENCE = "Licence Ouverte"
DOCS = "https://geo.api.gouv.fr/decoupage-administratif"


class CommunesForm(BaseModel):
    departement: Optional[str] = Field(
        None,
        pattern=r"^(?:\d{2}|2[AB]|97\d)$",
        description="A département code (29, 2A, 971); blank: every commune",
    )


class DivisionsForm(BaseModel):
    level: Literal["departements", "regions"] = "departements"


def _communes(form: CommunesForm) -> dict:
    url = (
        f"{BASE}/departements/{form.departement}/communes"
        if form.departement
        else f"{BASE}/communes"
    )
    return {
        "url": url,
        "params": {
            "fields": "nom,code,codesPostaux,codeDepartement,codeRegion,population,surface,siren,codeEpci",
            "format": "json",
        },
        "records_path": "$",
        "pagination": {"type": "none"},
    }


def _divisions(form: DivisionsForm) -> dict:
    return {
        "url": f"{BASE}/{form.level}",
        "params": {"format": "json"},
        "records_path": "$",
        "pagination": {"type": "none"},
    }


PRESETS = [
    Preset(
        id="geo-communes",
        title="Géo API — communes",
        description="The communes of a département (or of France): codes, postcodes, population, surface",
        producer=PRODUCER,
        licence=LICENCE,
        docs_url=DOCS,
        rate_limit_per_s=10,
        form=CommunesForm,
        build=_communes,
        name=lambda f: (
            f"Communes {f.departement}" if f.departement else "Communes de France"
        ),
    ),
    Preset(
        id="geo-divisions",
        title="Géo API — départements or regions",
        description="The départements or the regions, with their codes",
        producer=PRODUCER,
        licence=LICENCE,
        docs_url=DOCS,
        rate_limit_per_s=10,
        form=DivisionsForm,
        build=_divisions,
        name=lambda f: "Départements" if f.level == "departements" else "Régions",
    ),
]
