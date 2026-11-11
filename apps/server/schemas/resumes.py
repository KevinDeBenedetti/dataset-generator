"""Responses of the Reactive Resume routes (``/resumes``, services/reactive_resume.py)."""

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from server.schemas.jobs import JobRunRef
from server.schemas.recipes import HF_REPO_PATTERN


class ResumeSummary(BaseModel):
    id: str
    name: str
    slug: str
    tags: List[str] = Field(default_factory=list)
    is_public: bool
    is_locked: bool
    updated_at: Optional[str] = Field(None, description="Last change (ISO 8601)")


class ResumesOut(BaseModel):
    instance: str = Field(
        ..., description="The Reactive Resume instance read (scheme, host, port)"
    )
    resumes: List[ResumeSummary] = Field(
        ..., description="Every resume of the API key's account, newest change first"
    )


class ResumeLink(BaseModel):
    label: str
    url: str


class ResumeBasics(BaseModel):
    name: str = ""
    headline: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    website: str = ""
    facts: List[str] = Field(
        default_factory=list, description="Custom fields without a link"
    )
    links: List[ResumeLink] = Field(
        default_factory=list, description="Custom fields with one"
    )


class ResumeItem(BaseModel):
    id: str = Field(..., description="Unique in its section")
    title: str
    subtitle: str = Field("", description="Company, school, issuer…, location, level")
    period: str = ""
    text: str = Field("", description="The description as plain text, roles included")
    keywords: List[str] = Field(default_factory=list)
    url: str = Field("", description="An http(s) link, if any")


class ResumeSection(BaseModel):
    key: str = Field(..., description="The section's key; custom:<id> for a custom one")
    title: str
    items: List[ResumeItem]


class ResumeOut(BaseModel):
    id: str
    name: str
    slug: str
    updated_at: Optional[str] = None
    is_public: bool
    basics: ResumeBasics
    summary: str = Field("", description="The summary as plain text")
    sections: List[ResumeSection] = Field(
        ..., description="The visible sections, in reading order, hidden items left out"
    )


class ResumeDatasetIn(BaseModel):
    """A resume's dataset settings: where it publishes, in which language, on
    which model, and the preset that regenerates it by itself."""

    target_repo: str = Field(
        ...,
        max_length=193,
        pattern=HF_REPO_PATTERN,
        description="Hugging Face dataset it publishes to ('namespace/name' or 'name')",
    )
    language: Literal["auto", "en", "fr"] = Field(
        "auto", description="The pairs' language; auto: the resume's own"
    )
    model_ref: Optional[str] = Field(
        None, max_length=200, description="Model reference; null = your LLM"
    )
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


class ResumeDatasetOut(ResumeDatasetIn):
    resume_id: str
    title: str = Field("", description="The resume's name when the settings were saved")
    next_run_at: Optional[datetime] = Field(
        None, description="When the worker queues the next run"
    )
    latest_run: Optional[JobRunRef] = Field(
        None, description="The most recent run, scheduled or started by you"
    )
    updated_at: datetime


class ResumeRunRequest(BaseModel):
    full_refresh: bool = Field(
        False, description="Ignore the published version and regenerate every item"
    )
