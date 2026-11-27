"""API Sirene (INSEE) 3.11: the establishments (``/siret``) a multicriteria
query finds. It needs an account and an API key on portail-api.insee.fr, sent
in the ``X-INSEE-Api-Key-Integration`` header (saved as the data source's
secret). 30 requests a minute for open-data use; data under the Licence
Ouverte 2.0.

Deep paging is the ``curseur`` parameter: ``*`` first, then each answer's
``header.curseurSuivant``, the same one again on the last page.

A sole trader's legal unit is a person: their names, sex, birth date and
place and nationality come with every establishment. A new recipe of this
data source starts by dropping them (``STEPS``); keep them only for a private
dataset with a reason to.
"""

from pydantic import BaseModel, Field

from server.connectors.presets import Preset

BASE = "https://api.insee.fr/api-sirene/3.11"
PRODUCER = "Insee, répertoire Sirene"
LICENCE = "Licence Ouverte 2.0"
DOCS = (
    "https://portail-api.insee.fr/catalog/api/2ba0e549-5587-3ef1-9082-99cd865de66f/doc"
)
KEY_URL = "https://portail-api.insee.fr/"
PAGE = 1000

# The personal data of a sole trader, as the flattened record names it.
PERSONAL = [
    "uniteLegale.nomUniteLegale",
    "uniteLegale.nomUsageUniteLegale",
    "uniteLegale.prenom1UniteLegale",
    "uniteLegale.prenom2UniteLegale",
    "uniteLegale.prenom3UniteLegale",
    "uniteLegale.prenom4UniteLegale",
    "uniteLegale.prenomUsuelUniteLegale",
    "uniteLegale.pseudonymeUniteLegale",
    "uniteLegale.sexeUniteLegale",
    "uniteLegale.dateNaissanceUniteLegale",
    "uniteLegale.codeCommuneNaissanceUniteLegale",
    "uniteLegale.codePaysNaissanceUniteLegale",
    "uniteLegale.libelleNationaliteUniteLegale",
]
STEPS = [{"op": "mask", "column": c, "method": "drop"} for c in PERSONAL]


class EstablishmentsForm(BaseModel):
    q: str = Field(
        ...,
        min_length=3,
        max_length=1000,
        description="An INSEE multicriteria query, e.g. codeCommuneEtablissement:29019",
    )
    max_records: int = Field(10_000, ge=1, le=1_000_000)


def _establishments(form: EstablishmentsForm) -> dict:
    return {
        "url": f"{BASE}/siret",
        "params": {"q": form.q, "nombre": str(PAGE), "curseur": "*"},
        "records_path": "$.etablissements",
        "total_path": "$.header.total",
        "pagination": {
            "type": "cursor",
            "cursor_path": "$.header.curseurSuivant",
            "cursor_param": "curseur",
        },
        "max_records": form.max_records,
        "max_pages": 1000,
    }


PRESETS = [
    Preset(
        id="sirene-establishments",
        title="Sirene (INSEE) — establishments",
        description="The establishments a query finds (an INSEE API key is needed)",
        producer=PRODUCER,
        licence=LICENCE,
        docs_url=DOCS,
        rate_limit_per_s=0.5,
        form=EstablishmentsForm,
        build=_establishments,
        name=lambda f: f"Sirene — {f.q[:60]}",
        key_header="X-INSEE-Api-Key-Integration",
        key_url=KEY_URL,
        steps=STEPS,
    ),
]
