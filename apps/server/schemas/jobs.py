from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CorpusJobStatus(BaseModel):
    configured: bool
    github_username: bool
    github_token: bool
    hf_token: bool
    hf_dataset_repo: bool


class QADatasetJobStatus(BaseModel):
    configured: bool
    github_username: bool
    github_token: bool
    claude_credentials: bool
    hf_token: bool
    hf_qa_dataset_repo: bool


class JobsStatusResponse(BaseModel):
    corpus: CorpusJobStatus
    qa_dataset: QADatasetJobStatus


class CorpusSyncRequest(BaseModel):
    sources: Optional[List[str]] = Field(
        None,
        description="Splits to build: profile, github, github_code, github_docs "
        "(default: all four)",
    )
    dry_run: bool = Field(
        False,
        description="Build the corpus but skip publishing it to Hugging Face",
    )


class CorpusSyncResponse(BaseModel):
    manifest: Dict[str, Any]
    url: Optional[str] = Field(
        None, description="Hub dataset URL, or null on a dry run"
    )
    dry_run: bool


class QADatasetSyncRequest(BaseModel):
    max_repos: Optional[int] = Field(
        None,
        ge=1,
        description="Cap on repos processed (default: 15) — lower this for a "
        "cheap test run",
    )
    dry_run: bool = Field(
        False,
        description="Generate pairs but skip publishing them to Hugging Face",
    )


class QADatasetSyncResponse(BaseModel):
    repo: Optional[str] = None
    url: Optional[str] = Field(
        None, description="Hub dataset URL, or null on a dry run"
    )
    records: int
    dropped: int
    errors: List[str] = []
    dry_run: bool
