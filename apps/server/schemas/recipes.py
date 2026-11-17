"""Dataset recipes (``/recipes``, services/recipes.py)."""

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from server.schemas.jobs import JobRunRef
from server.services.github_browse import valid_doc_path

# A Hugging Face repo id, with or without its namespace (completed at
# generation time with the one saved in Settings).
HF_REPO_PATTERN = (
    r"^(?:[A-Za-z0-9][A-Za-z0-9._-]{0,95}/)?[A-Za-z0-9][A-Za-z0-9._-]{0,95}$"
)
GITHUB_REPO_PATTERN = r"^[A-Za-z0-9._-]{1,100}$"

MAX_SOURCES = 200
MAX_DOCS_PER_SOURCE = 20


class RecipeSource(BaseModel):
    """One repo of the recipe and what of it feeds the dataset."""

    repo: str = Field(..., pattern=GITHUB_REPO_PATTERN, description="Repo name")
    readme: bool = Field(True, description="Generate from its README and metadata")
    docs: Optional[List[str]] = Field(
        None,
        max_length=MAX_DOCS_PER_SOURCE,
        description="docs/ files to generate from; null = the default pick, [] = none",
    )

    @field_validator("docs")
    @classmethod
    def _docs_are_docs(cls, docs: Optional[List[str]]) -> Optional[List[str]]:
        if docs is None:
            return None
        bad = [d for d in docs if not valid_doc_path(d)]
        if bad:
            raise ValueError(f"not a Markdown or text file under docs/: {bad[0]}")
        return list(dict.fromkeys(docs))


class RecipeIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    target_repo: str = Field(
        ...,
        max_length=193,
        pattern=HF_REPO_PATTERN,
        description="Hugging Face repo it publishes to ('namespace/name' or 'name')",
    )
    include_profile: bool = Field(True, description="Add the GitHub profile facts")
    sources: List[RecipeSource] = Field(default_factory=list, max_length=MAX_SOURCES)
    model_ref: Optional[str] = Field(
        None, max_length=200, description="Model reference; null = the jobs default"
    )

    @field_validator("name")
    @classmethod
    def _strip_name(cls, name: str) -> str:
        name = name.strip()
        if not name:
            raise ValueError("the name can't be blank")
        return name

    @model_validator(mode="after")
    def _one_entry_per_repo(self) -> "RecipeIn":
        repos = [s.repo.lower() for s in self.sources]
        if len(repos) != len(set(repos)):
            raise ValueError("each repo can appear only once")
        return self


class RecipeOut(RecipeIn):
    id: str
    created_at: datetime
    updated_at: datetime
    latest_run: Optional[JobRunRef] = Field(
        None, description="The recipe's most recent generation, if any"
    )


class RecipeRunRequest(BaseModel):
    full_refresh: bool = Field(
        False, description="Ignore the published version and regenerate every source"
    )
    model_ref: Optional[str] = Field(
        None, max_length=200, description="Model for this run; null = the recipe's"
    )


class RecipeScheduleIn(BaseModel):
    """When a recipe's dataset regenerates by itself, and what a scheduled
    run does with its result."""

    every: Optional[Literal["day", "week", "month"]] = Field(
        None,
        description="Regenerate every day, week or month; null = only when you "
        "start it",
    )
    at_hour: int = Field(3, ge=0, le=23, description="Hour of a scheduled run (UTC)")
    at_minute: int = Field(0, ge=0, le=59, description="Minute of a scheduled run")
    publish: bool = Field(
        True,
        description="A scheduled run publishes what passes the checks and keeps "
        "the rest for review; off: it stops at a draft",
    )


class RecipeScheduleOut(RecipeScheduleIn):
    recipe_id: str
    next_run_at: Optional[datetime] = Field(
        None, description="When the worker queues the next run"
    )
    latest_run: Optional[JobRunRef] = Field(
        None, description="The most recent scheduled run"
    )
    updated_at: datetime


class RecipesOut(BaseModel):
    recipes: List[RecipeOut]
