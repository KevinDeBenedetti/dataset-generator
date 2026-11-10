"""Responses of the Reactive Resume routes (``/resumes``, services/reactive_resume.py)."""

from typing import List, Optional

from pydantic import BaseModel, Field


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
