"""Ready-made REST data sources for French public APIs (#320).

A preset turns a short form (the few parameters that matter) into a ``rest``
connector config, with the API's producer, licence and rate limit. The config
keeps the preset's name: its rate limit and depth cap hold even when the
config is edited, and a new recipe of the data source starts with the
preset's steps (Sirene's: the personal data of sole traders dropped).

Each module's facts — base URL, paging, limits, licence — were read from the
API's own documentation and its data.gouv.fr record (docs/sources.md lists
them).
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type

from pydantic import BaseModel


@dataclass(frozen=True)
class Preset:
    id: str
    title: str
    description: str
    producer: str
    # The licence as the data source states it (hub/licences.py resolves it).
    licence: str
    docs_url: str
    # Calls a second at most, below the API's own limit: the server's address
    # is shared by every user.
    rate_limit_per_s: float
    form: Type[BaseModel]
    build: Callable[[Any], Dict[str, Any]]
    name: Callable[[Any], str]
    # How deep paging may go (an API that refuses past it), if it caps it.
    max_records: Optional[int] = None
    # The API key goes in this header (a data source secret), if one is needed.
    key_header: Optional[str] = None
    key_url: Optional[str] = None
    # The first steps of a new recipe of this data source.
    steps: List[Dict[str, Any]] = field(default_factory=list)

    def config(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """The ``rest`` config of this preset for ``params`` (validated)."""
        form = self.form.model_validate(params)
        out = {
            **self.build(form),
            "producer": self.producer,
            "rate_limit_per_s": self.rate_limit_per_s,
            "preset": self.id,
        }
        if self.max_records is not None:
            out["max_records"] = min(
                out.get("max_records", self.max_records), self.max_records
            )
        if self.key_header:
            out["auth"] = {"type": "header", "name": self.key_header}
        return out

    def describe(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "producer": self.producer,
            "licence": self.licence,
            "docs_url": self.docs_url,
            "rate_limit_per_s": self.rate_limit_per_s,
            "max_records": self.max_records,
            "needs_key": self.key_header is not None,
            "key_url": self.key_url,
            "form_schema": self.form.model_json_schema(),
            "steps": self.steps,
        }


def _all() -> Dict[str, Preset]:
    from server.connectors.presets import adresse, annuaire, geo, sirene

    return {p.id: p for m in (geo, adresse, annuaire, sirene) for p in m.PRESETS}


_PRESETS: Optional[Dict[str, Preset]] = None


def presets() -> Dict[str, Preset]:
    global _PRESETS
    if _PRESETS is None:
        _PRESETS = _all()
    return _PRESETS


def get_preset(preset_id: str) -> Optional[Preset]:
    return presets().get(preset_id)
