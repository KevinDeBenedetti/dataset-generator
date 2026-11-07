"""Responses of the GitHub browse routes (``/github/*``, services/github_browse.py)."""

from typing import List, Optional

from pydantic import BaseModel, Field


class GitHubRateLimit(BaseModel):
    limit: int = Field(..., description="Requests per hour the quota allows")
    remaining: int
    reset_at: Optional[str] = Field(
        None, description="When the quota resets (ISO 8601)"
    )
    authenticated: bool = Field(
        ..., description="True when a GitHub token raises the quota (60 → 5000)"
    )


class GitHubProfileOut(BaseModel):
    login: str
    name: Optional[str] = None
    bio: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None
    blog: Optional[str] = None
    html_url: str
    avatar_url: Optional[str] = None
    public_repos: int
    followers: int
    following: int
    rate_limit: GitHubRateLimit


class GitHubRepoSummary(BaseModel):
    name: str
    full_name: str
    description: Optional[str] = None
    language: Optional[str] = None
    stars: int
    topics: List[str] = Field(default_factory=list)
    fork: bool
    archived: bool
    eligible: bool = Field(
        ..., description="What a generation takes: public, not a fork, not archived"
    )
    pushed_at: Optional[str] = None
    html_url: str
    homepage: Optional[str] = None
    default_branch: str


class GitHubReposOut(BaseModel):
    username: str
    total: int
    repos: List[GitHubRepoSummary]


class GitHubDocEntry(BaseModel):
    path: str
    size: int
    readable: bool = Field(..., description="Under the size a generation reads")
    selected_by_default: bool = Field(
        ..., description="Read by a generation that picks no docs file itself"
    )


class GitHubLimits(BaseModel):
    readme_chars: int
    doc_chars: int
    doc_bytes: int
    docs_per_repo: int


class GitHubRepoDetail(BaseModel):
    name: str
    full_name: str
    description: Optional[str] = None
    stars: int
    topics: List[str] = Field(default_factory=list)
    language: Optional[str] = None
    homepage: Optional[str] = None
    html_url: str
    default_branch: str
    readme: Optional[str] = Field(
        None, description="Cleaned and cut as the model sees it; null without one"
    )
    readme_truncated: bool
    technologies: List[str] = Field(
        default_factory=list, description="Detected from the dependency manifests"
    )
    docs: List[GitHubDocEntry]
    model_input: str = Field(
        ..., description="The exact overview text sent to the model"
    )
    limits: GitHubLimits


class GitHubDocContent(BaseModel):
    path: str
    content: str = Field(..., description="Cut at max_chars, as the model reads it")
    truncated: bool
    max_chars: int
