"""Data sources (``/data-sources``) and recipes (``/recipes``), services/data_sources.py."""

import json
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from server.schemas.recipes import HF_REPO_PATTERN

CONNECTOR_PATTERN = r"^[a-z][a-z0-9_-]{0,63}$"
MAX_CONFIG_BYTES = 64 * 1024
MAX_STEPS = 100


def _bounded_json(value: Any, what: str) -> Any:
    if len(json.dumps(value, default=str)) > MAX_CONFIG_BYTES:
        raise ValueError(f"{what} is too large ({MAX_CONFIG_BYTES // 1024} KB at most)")
    return value


class DataSourceIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    connector: str = Field(..., pattern=CONNECTOR_PATTERN)
    config: Dict[str, Any] = Field(default_factory=dict)
    licence: Optional[str] = Field(
        None, max_length=200, description="The licence the data comes with"
    )

    @field_validator("name")
    @classmethod
    def _strip(cls, name: str) -> str:
        name = name.strip()
        if not name:
            raise ValueError("name must not be blank")
        return name

    @field_validator("config")
    @classmethod
    def _small(cls, config: Dict[str, Any]) -> Dict[str, Any]:
        return _bounded_json(config, "config")


class DataSourcePatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    config: Optional[Dict[str, Any]] = None
    licence: Optional[str] = Field(None, max_length=200)

    @field_validator("config")
    @classmethod
    def _small(cls, config: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        return None if config is None else _bounded_json(config, "config")


class DataSourceOut(BaseModel):
    id: str
    name: str
    connector: str
    config: Dict[str, Any]
    secret_kind: Optional[str] = None
    licence: Optional[str] = None
    last_fingerprint: Optional[str] = None
    last_fetched_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class DataSourcesOut(BaseModel):
    data_sources: List[DataSourceOut]


OutputKindLiteral = Literal["table", "qa", "corpus"]
VisibilityLiteral = Literal["private", "public"]


class SourceRecipeIn(BaseModel):
    """A recipe: what to do with one data source."""

    name: str = Field(..., min_length=1, max_length=100)
    data_source_id: str = Field(..., min_length=1, max_length=64)
    steps: List[Dict[str, Any]] = Field(default_factory=list, max_length=MAX_STEPS)
    output_kind: OutputKindLiteral = "table"
    output_options: Dict[str, Any] = Field(default_factory=dict)
    target_repo: str = Field(..., max_length=193, pattern=HF_REPO_PATTERN)
    visibility: VisibilityLiteral = "private"
    model_ref: Optional[str] = Field(None, max_length=200)

    @field_validator("name")
    @classmethod
    def _strip(cls, name: str) -> str:
        name = name.strip()
        if not name:
            raise ValueError("name must not be blank")
        return name

    @field_validator("steps")
    @classmethod
    def _small_steps(cls, steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return _bounded_json(steps, "steps")

    @field_validator("output_options")
    @classmethod
    def _small_options(cls, options: Dict[str, Any]) -> Dict[str, Any]:
        return _bounded_json(options, "output_options")


class SourceRecipePatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    steps: Optional[List[Dict[str, Any]]] = Field(None, max_length=MAX_STEPS)
    output_kind: Optional[OutputKindLiteral] = None
    output_options: Optional[Dict[str, Any]] = None
    target_repo: Optional[str] = Field(None, max_length=193, pattern=HF_REPO_PATTERN)
    visibility: Optional[VisibilityLiteral] = None
    model_ref: Optional[str] = Field(None, max_length=200)

    @field_validator("steps")
    @classmethod
    def _small_steps(cls, steps):
        return None if steps is None else _bounded_json(steps, "steps")

    @field_validator("output_options")
    @classmethod
    def _small_options(cls, options):
        return None if options is None else _bounded_json(options, "output_options")


class SourceRecipeOut(BaseModel):
    id: str
    name: str
    data_source_id: str
    steps: List[Dict[str, Any]]
    output_kind: str
    output_options: Dict[str, Any]
    target_repo: str
    visibility: str
    model_ref: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class SourceRecipesOut(BaseModel):
    recipes: List[SourceRecipeOut]
