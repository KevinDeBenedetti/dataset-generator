"""Licences: what a data source states, as the Hub's ``license`` value, and
whether it allows a public dataset (ADR 0005).

data.gouv.fr names its licences by id (``lov2``, ``odc-odbl``…); an uploaded
file's licence is what the user typed. Both are mapped here; anything not
recognised is ``unknown`` and keeps the dataset private.
"""

import re
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Licence:
    hf: str  # the Hub's `license` value
    name: str  # how the card names it
    url: Optional[str]
    redistributable: bool
    # Licence Ouverte / Etalab 2.0 asks for a "Source: …" mention.
    etalab: bool = False


ETALAB = Licence(
    "etalab-2.0",
    "Licence Ouverte / Open Licence 2.0 (Etalab)",
    "https://www.etalab.gouv.fr/licence-ouverte-open-licence/",
    True,
    etalab=True,
)
ODBL = Licence(
    "odbl",
    "Open Database License (ODbL)",
    "https://opendatacommons.org/licenses/odbl/",
    True,
)
ODC_BY = Licence(
    "odc-by",
    "Open Data Commons Attribution License",
    "https://opendatacommons.org/licenses/by/",
    True,
)
CC_BY = Licence(
    "cc-by-4.0",
    "Creative Commons Attribution 4.0",
    "https://creativecommons.org/licenses/by/4.0/",
    True,
)
CC_BY_SA = Licence(
    "cc-by-sa-4.0",
    "Creative Commons Attribution-ShareAlike 4.0",
    "https://creativecommons.org/licenses/by-sa/4.0/",
    True,
)
CC0 = Licence(
    "cc0-1.0",
    "Creative Commons Zero 1.0",
    "https://creativecommons.org/publicdomain/zero/1.0/",
    True,
)
UNKNOWN = Licence("unknown", "not stated", None, False)
OTHER = Licence("other", "other (see the source)", None, False)

# data.gouv.fr licence ids.
_DATAGOUV = {
    "lov2": ETALAB,
    "fr-lo": ETALAB,
    "odc-odbl": ODBL,
    "odc-by": ODC_BY,
    "cc-by": CC_BY,
    "cc-by-sa": CC_BY_SA,
    "cc-zero": CC0,
    "odc-pddl": CC0,
    "notspecified": UNKNOWN,
}
# What a user may type, matched loosely.
_PATTERNS = (
    (r"\b(lov2|fr-lo|etalab|licence ouverte|open licen[cs]e)\b", ETALAB),
    (r"\bodbl\b|open database licen[cs]e", ODBL),
    (r"\bodc[- ]?by\b", ODC_BY),
    (r"\bcc[- ]?by[- ]?sa\b", CC_BY_SA),
    (r"\bcc[- ]?by\b", CC_BY),
    (r"\bcc[- ]?0\b|\bcc[- ]?zero\b|public domain|domaine public", CC0),
)


def resolve(stated: Optional[str]) -> Licence:
    """The licence ``stated`` names (a data.gouv.fr id or free text)."""
    if not stated or not stated.strip():
        return UNKNOWN
    text = stated.strip().lower()
    if text in _DATAGOUV:
        return _DATAGOUV[text]
    if text.startswith("other-"):
        return OTHER
    for pattern, licence in _PATTERNS:
        if re.search(pattern, text):
            return licence
    return OTHER


def public_refusal(stated: Optional[str]) -> Optional[str]:
    """Why a dataset under ``stated`` can't be public, or None when it can."""
    licence = resolve(stated)
    if licence.redistributable:
        return None
    if licence is UNKNOWN:
        return "The data source states no licence: a public dataset needs one that allows it"
    return f"The licence '{stated}' is not one known to allow redistribution: keep the dataset private"
