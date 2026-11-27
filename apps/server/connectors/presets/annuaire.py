"""API Annuaire de l'administration et des services publics
(service-public.gouv.fr, an Opendatasoft portal): the public offices of a
département — town halls, prefectures, agencies — with their addresses,
phones and opening hours. No key; data under the Licence Ouverte.

Paging is ``limit`` (100 at most) + ``offset``, and the portal refuses an
offset + limit above 10 000: a département's offices fit (the Finistère has
under a thousand), France's 94 000 do not, so the form asks for a
département. The ``affectation_personne`` field names the people in charge
of an office: the preset never asks for it (``select``).
"""

from typing import Optional

from pydantic import BaseModel, Field

from server.connectors.presets import Preset

BASE = (
    "https://api-lannuaire.service-public.gouv.fr/api/explore/v2.1/catalog/"
    "datasets/api-lannuaire-administration/records"
)
PRODUCER = "Direction de l'information légale et administrative (Premier ministre)"
LICENCE = "Licence Ouverte"
DOCS = "https://api-lannuaire.service-public.gouv.fr/api/explore/v2.1/swagger.json"
# The fields kept: no names of people, no personal e-mail.
FIELDS = (
    "id,nom,sigle,categorie,code_insee_commune,adresse,telephone,site_internet,"
    "url_service_public,siret,siren,date_modification,pivot,plage_ouverture"
)
MAX_DEPTH = 10_000


class OfficesForm(BaseModel):
    departement: str = Field(
        ...,
        pattern=r"^(?:\d{2}|2[AB]|97\d)$",
        description="A département code (29, 2A, 971)",
    )
    service: Optional[str] = Field(
        None,
        pattern=r"^[a-z_]{2,60}$",
        description="Only this kind of office (mairie, prefecture, caf…)",
    )


def _offices(form: OfficesForm) -> dict:
    where = f'startswith(code_insee_commune, "{form.departement}")'
    if form.service:
        where += f' and search(pivot, "{form.service}")'
    return {
        "url": BASE,
        "params": {"where": where, "select": FIELDS},
        "records_path": "$.results",
        "total_path": "$.total_count",
        "pagination": {
            "type": "offset",
            "size_param": "limit",
            "size": 100,
            "offset_param": "offset",
        },
        "max_pages": MAX_DEPTH // 100,
    }


PRESETS = [
    Preset(
        id="annuaire-offices",
        title="Annuaire de l'administration — public offices",
        description="The public offices of a département: addresses, phones, opening hours",
        producer=PRODUCER,
        licence=LICENCE,
        docs_url=DOCS,
        rate_limit_per_s=5,
        form=OfficesForm,
        build=_offices,
        name=lambda f: (
            f"Services publics {f.departement}"
            + (f" ({f.service})" if f.service else "")
        ),
        max_records=MAX_DEPTH,
    ),
]
