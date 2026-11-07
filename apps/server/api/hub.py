"""The Hub viewer: datasets read from Hugging Face, the source of truth.

Every route reads with the caller's own Hugging Face token (services/hub.py),
so the Hub decides what each user can see: a repo their token can't read
answers 404, like an unknown one.

Plain ``def`` routes: each one makes blocking Hub calls and may load a split
into memory, so FastAPI runs them in its threadpool.
"""

import json
import logging
from typing import Callable, List, Literal, Optional, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import TypeAdapter, ValidationError

from server.api.deps import get_credentials
from server.schemas.hub import (
    HubCommits,
    HubCompare,
    HubDatasetDetail,
    HubDatasetList,
    HubFullRow,
    HubRowFilter,
    HubRows,
    HubStatistics,
)
from server.services import hub
from server.services.credentials import Credentials
from server.services.huggingface import HuggingFaceNotConfiguredError

router = APIRouter(prefix="/hub", tags=["hub"])
logger = logging.getLogger(__name__)

T = TypeVar("T")

# One segment of a repo id; services/hub.py validates it fully.
Owner = Path(..., max_length=96, description="User or organization on the Hub")
Name = Path(..., max_length=96, description="Dataset repo name")
Revision = Query(
    None,
    max_length=256,
    description="Branch, tag or commit sha (default branch if empty)",
)
ConfigName = Query(None, alias="config", max_length=256, description="Config name")
Split = Query(None, max_length=512, description="Split name")

_FILTERS = TypeAdapter(List[HubRowFilter])


def _call(fn: Callable[[], T], what: str) -> T:
    """Run a viewer call, mapping its errors to HTTP answers.

    5xx answers carry a generic message: the Hub's own error text can name
    internals (URLs, request ids) and is logged instead.
    """
    try:
        return fn()
    except HuggingFaceNotConfiguredError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except hub.HubNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except hub.HubTooLargeError as e:
        raise HTTPException(status_code=413, detail=str(e)) from e
    except hub.HubBadQueryError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except hub.HubUnreadableError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except hub.HubUnavailableError:
        logger.exception("Hub viewer: %s failed", what)
        raise HTTPException(
            status_code=502,
            detail="The Hugging Face Hub didn't answer. Try again shortly.",
        ) from None
    except Exception:
        logger.exception("Hub viewer: %s failed", what)
        raise HTTPException(status_code=502, detail=f"Reading {what} failed") from None


def _parse_filters(raw: Optional[str]) -> List[hub.RowFilter]:
    if not raw:
        return []
    try:
        parsed = _FILTERS.validate_python(json.loads(raw))
    except (ValueError, ValidationError):
        raise HTTPException(
            status_code=400,
            detail="filters must be a JSON list of {column, op, value} objects",
        ) from None
    return [hub.RowFilter(f.column, f.op, f.value) for f in parsed]


def _repo(owner: str, name: str) -> str:
    try:
        return hub.repo_id_of(owner, name)
    except hub.HubNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get(
    "/datasets", response_model=HubDatasetList, summary="List your Hub datasets"
)
def get_hub_datasets(
    author: Optional[str] = Query(
        None, max_length=96, description="One of your namespaces (default: your own)"
    ),
    creds: Credentials = Depends(get_credentials),
):
    """The dataset repos of your Hugging Face account or one of its organizations,
    private ones included, most recently updated first."""
    return _call(lambda: hub.list_datasets(creds, author), "the dataset list")


@router.get(
    "/datasets/{owner}/{name}",
    response_model=HubDatasetDetail,
    summary="A Hub dataset at one revision",
)
def get_hub_dataset(
    owner: str = Owner,
    name: str = Name,
    revision: Optional[str] = Revision,
    creds: Credentials = Depends(get_credentials),
):
    """Metadata, card, files, tables (configs and splits) and refs of a dataset,
    all read at one commit (``sha``)."""
    repo_id = _repo(owner, name)
    return _call(lambda: hub.overview(creds, repo_id, revision), repo_id)


@router.get(
    "/datasets/{owner}/{name}/rows",
    response_model=HubRows,
    summary="A page of rows, with search, filters and sort",
)
def get_hub_rows(
    owner: str = Owner,
    name: str = Name,
    revision: Optional[str] = Revision,
    config_name: Optional[str] = ConfigName,
    split: Optional[str] = Split,
    offset: int = Query(0, ge=0, le=10_000_000),
    length: int = Query(25, ge=1, le=hub.MAX_PAGE_LENGTH),
    q: Optional[str] = Query(
        None,
        max_length=200,
        description="Case-insensitive text search, nested fields included",
    ),
    filters: Optional[str] = Query(
        None,
        max_length=4000,
        description='JSON list, e.g. [{"column": "category", "op": "eq", "value": "docs"}]',
    ),
    sort: Optional[str] = Query(None, max_length=200, description="Column to sort by"),
    order: Literal["asc", "desc"] = Query("asc"),
    creds: Credentials = Depends(get_credentials),
):
    """One page of a split. Long text cells are cut (``truncated_cells``)."""
    repo_id = _repo(owner, name)
    parsed = _parse_filters(filters)
    return _call(
        lambda: hub.rows(
            creds,
            repo_id,
            revision=revision,
            config_name=config_name,
            split=split,
            offset=offset,
            length=length,
            query=q,
            filters=parsed,
            sort=sort,
            order=order,
        ),
        f"the rows of {repo_id}",
    )


@router.get(
    "/datasets/{owner}/{name}/row",
    response_model=HubFullRow,
    summary="One full row",
)
def get_hub_row(
    owner: str = Owner,
    name: str = Name,
    row_idx: int = Query(..., ge=0, description="Position of the row in the split"),
    revision: Optional[str] = Revision,
    config_name: Optional[str] = ConfigName,
    split: Optional[str] = Split,
    creds: Credentials = Depends(get_credentials),
):
    """A row with every cell in full."""
    repo_id = _repo(owner, name)
    return _call(
        lambda: hub.row(
            creds,
            repo_id,
            row_idx,
            revision=revision,
            config_name=config_name,
            split=split,
        ),
        f"a row of {repo_id}",
    )


@router.get(
    "/datasets/{owner}/{name}/statistics",
    response_model=HubStatistics,
    summary="Per-column statistics of a split",
)
def get_hub_statistics(
    owner: str = Owner,
    name: str = Name,
    revision: Optional[str] = Revision,
    config_name: Optional[str] = ConfigName,
    split: Optional[str] = Split,
    creds: Credentials = Depends(get_credentials),
):
    """Types, nulls, length and value distributions, labels and duplicates."""
    repo_id = _repo(owner, name)
    return _call(
        lambda: hub.statistics(
            creds, repo_id, revision=revision, config_name=config_name, split=split
        ),
        f"the statistics of {repo_id}",
    )


@router.get(
    "/datasets/{owner}/{name}/commits",
    response_model=HubCommits,
    summary="The dataset's versions (commits)",
)
def get_hub_commits(
    owner: str = Owner,
    name: str = Name,
    creds: Credentials = Depends(get_credentials),
):
    """Newest first. Every commit is a version of the dataset."""
    repo_id = _repo(owner, name)
    return _call(lambda: hub.commits(creds, repo_id), f"the history of {repo_id}")


@router.get(
    "/datasets/{owner}/{name}/compare",
    response_model=HubCompare,
    summary="What changed in a split between two versions",
)
def get_hub_compare(
    owner: str = Owner,
    name: str = Name,
    base: str = Query(..., max_length=256, description="Older revision"),
    head: Optional[str] = Query(
        None, max_length=256, description="Newer revision (default branch if empty)"
    ),
    config_name: Optional[str] = ConfigName,
    split: Optional[str] = Split,
    creds: Credentials = Depends(get_credentials),
):
    """Rows added, removed and changed, matched by ``id`` when every row has a
    unique one, else by content."""
    repo_id = _repo(owner, name)
    return _call(
        lambda: hub.compare(
            creds, repo_id, base=base, head=head, config_name=config_name, split=split
        ),
        f"two versions of {repo_id}",
    )
