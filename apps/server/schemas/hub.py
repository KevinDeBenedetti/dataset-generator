"""Responses of the Hub viewer (``/hub/*``, services/hub.py).

Rows are whatever the dataset holds, so a row is a free-form JSON object; the
structure around it (columns, pagination, statistics) is typed.
"""

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, StrictBool

from server.schemas.dataset import HuggingFaceDataset


class HubDatasetList(BaseModel):
    namespace: str = Field(..., description="The namespace listed")
    namespaces: List[str] = Field(
        ..., description="Every namespace the token can list: account, orgs, saved one"
    )
    total: int
    datasets: List[HuggingFaceDataset]


class HubFile(BaseModel):
    path: str
    size: Optional[int] = Field(None, description="Bytes; null when the Hub didn't say")
    lfs: bool


class HubView(BaseModel):
    """One table of the dataset: a config's split, or an extra data file."""

    config: str
    split: str
    files: List[str]
    num_bytes: Optional[int] = None
    extra: bool = Field(
        False, description="A data file outside the dataset's declared splits"
    )


class HubRef(BaseModel):
    name: str
    target_commit: str


class HubRefs(BaseModel):
    branches: List[HubRef] = Field(default_factory=list)
    tags: List[HubRef] = Field(default_factory=list)


class HubCard(BaseModel):
    markdown: Optional[str] = Field(
        None, description="README body without its YAML header; null without a card"
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)


class HubDatasetDetail(HuggingFaceDataset):
    """A dataset repo at one commit: metadata, card, files and tables."""

    # Narrower than the listing's optional sha: a detail is always read at one
    # commit, and nothing writes the field back.
    sha: str = Field(  # ty: ignore[invalid-mutable-override]
        ..., description="The commit everything on the page was read at"
    )
    revision: Optional[str] = Field(None, description="The revision asked for")
    card: HubCard
    files: List[HubFile]
    views: List[HubView]
    refs: HubRefs
    max_view_bytes: int = Field(..., description="Largest table the viewer loads")


class HubFeature(BaseModel):
    name: str
    type: str = Field(
        ..., description="Arrow type, e.g. string, double, list<item: string>"
    )
    kind: str = Field(
        ...,
        description="string, number, bool, list, object, datetime, binary, null or other",
    )


class HubQAColumns(BaseModel):
    """Which columns hold the question, the answer and the context."""

    question: str
    answer: str
    context: Optional[str] = None


class HubRow(BaseModel):
    row_idx: int = Field(..., description="Position of the row in the split")
    row: Dict[str, Any]
    truncated_cells: List[str] = Field(
        default_factory=list, description="Columns cut short; GET .../row for all of it"
    )


class HubSplitRef(BaseModel):
    repo_id: str
    sha: str
    config: str
    split: str


class HubRows(HubSplitRef):
    features: List[HubFeature]
    qa: Optional[HubQAColumns] = None
    rows: List[HubRow]
    num_rows_total: int = Field(..., description="Rows in the split")
    num_rows_matched: int = Field(..., description="Rows left after search and filters")
    offset: int
    length: int


class HubFullRow(HubSplitRef):
    row_idx: int
    row: Dict[str, Any]


class HubHistogramBin(BaseModel):
    start: float
    end: float
    count: int


class HubNumericSummary(BaseModel):
    min: Optional[float] = None
    max: Optional[float] = None
    mean: Optional[float] = None
    median: Optional[float] = None
    histogram: List[HubHistogramBin] = Field(default_factory=list)


class HubCategoryValue(BaseModel):
    value: Any
    count: int


class HubCategories(BaseModel):
    distinct: int
    values: List[HubCategoryValue]
    other_count: int = Field(
        ..., description="Rows holding a value outside the top ones"
    )


class HubBooleanCounts(BaseModel):
    true: int
    false: int


class HubColumnStats(BaseModel):
    name: str
    type: str
    kind: str
    count: int
    null_count: int
    lengths: Optional[HubNumericSummary] = Field(
        None, description="Characters per value (strings) or items per value (lists)"
    )
    number: Optional[HubNumericSummary] = None
    booleans: Optional[HubBooleanCounts] = None
    categories: Optional[HubCategories] = Field(
        None, description="Value counts, when the values are repeated labels"
    )


class HubDuplicates(BaseModel):
    column: str
    duplicate_rows: int = Field(
        ...,
        description="Rows repeating an earlier row's value (case and spaces ignored)",
    )


class HubStatistics(HubSplitRef):
    num_rows: int
    num_columns: int
    columns: List[HubColumnStats]
    qa: Optional[HubQAColumns] = None
    duplicates: Optional[HubDuplicates] = None


class HubCommit(BaseModel):
    id: str
    title: str
    message: str
    authors: List[str]
    created_at: Optional[str] = None


class HubCommits(BaseModel):
    repo_id: str
    total: int
    commits: List[HubCommit]


class HubChangedRow(BaseModel):
    before: Dict[str, Any]
    after: Dict[str, Any]


class HubCompare(BaseModel):
    repo_id: str
    config: str
    split: str
    base: str = Field(..., description="Commit compared from")
    head: str = Field(..., description="Commit compared to")
    key: str = Field(
        ..., description="'id' when rows were matched by id, else 'content'"
    )
    base_rows: int
    head_rows: int
    added: int
    removed: int
    changed: int
    unchanged: int
    added_examples: List[Dict[str, Any]]
    removed_examples: List[Dict[str, Any]]
    changed_examples: List[HubChangedRow]


class HubRowFilter(BaseModel):
    """One filter of ``GET .../rows`` (sent as a JSON list in ``filters``)."""

    column: str = Field(..., max_length=200)
    op: Literal["eq", "ne", "lt", "lte", "gt", "gte", "contains", "null", "not_null"]
    value: Optional[Union[StrictBool, float, str]] = Field(None)
