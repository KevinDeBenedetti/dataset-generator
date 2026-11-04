"""Read datasets from the Hugging Face Hub, the source of truth.

The app keeps no copy of a published dataset: the Datasets section reads every
page from the Hub, with the caller's own token, at a pinned commit.

How a read works:

1. :func:`resolve` fetches the repo's metadata at a revision (branch, tag or
   commit sha). That one call is the access check: a repo the caller's token
   can't read is "not found", whoever else has opened it. It also pins the
   commit sha and lists every file with its size.
2. :func:`views` turns the file list (and the card's ``configs`` block) into
   the dataset's configs and splits, following the Hub viewer's rules.
3. :func:`load_split` downloads a split's data files at that sha and reads them
   into one Arrow table, cached by (repo, sha, config, split). Content at a sha
   never changes, so a cached table is never stale, and since every request
   goes through :func:`resolve` first, the cache never serves a repo to a
   token that can't read it.
4. Rows, search, filters, sorting, statistics and version comparisons all run
   on that table with ``pyarrow.compute``.

Why not the Hub's dataset viewer API? It serves private datasets only to PRO
accounts and Enterprise organizations, and every dataset this app publishes is
private.
"""

import fnmatch
import hashlib
import json
import logging
import math
import os
import re
import tempfile
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from datetime import time as time_of_day
from decimal import Decimal
from typing import (
    Any,
    Callable,
    Dict,
    Hashable,
    Iterable,
    List,
    Optional,
    Tuple,
    TypeVar,
)

import httpx
import pyarrow as pa
import pyarrow.compute as _compute

from server.core.config import config
from server.services.credentials import HF_TOKEN, Credentials
from server.services.huggingface import (
    _ANSWER_KEYS,
    _CONTEXT_KEYS,
    _NON_DATA_FILENAMES,
    _QUESTION_KEYS,
    HuggingFaceNotConfiguredError,
    _api,
    _card_metadata,
    _json_safe,
    _require_token,
)

logger = logging.getLogger(__name__)

# pyarrow builds its compute functions at import time from the C++ function
# registry, so a type checker has nothing to read: typed as Any once, here,
# instead of an ignore comment on every call.
pc: Any = _compute

T = TypeVar("T")

# Hidden column added to every loaded split: the row's position in the split as
# published, so a row keeps its index through search, filters and sorting.
ROW_IDX = "__row_idx__"

# Data file formats the viewer reads. ``.json`` may hold one document (a list of
# rows) or JSON Lines; the others are read natively by Arrow.
DATA_EXTENSIONS = (".jsonl", ".ndjson", ".json", ".csv", ".tsv", ".parquet")
# Files outside every declared split are still offered as extra views when they
# are unambiguously tabular. A stray ``.json`` is usually metadata, not rows.
EXTRA_EXTENSIONS = (".jsonl", ".ndjson", ".csv", ".tsv", ".parquet")
# Written by the app's own jobs next to the data: state, not rows.
APP_STATE_FILES = {"manifest.json"}

# A split spread over more files than this is refused, whatever their size.
MAX_FILES_PER_SPLIT = 500
# A card larger than this is not rendered.
MAX_CARD_BYTES = 1024 * 1024
# String cells longer than this are cut in row listings; the full row is one
# request away (:func:`row`).
MAX_CELL_CHARS = 5_000
MAX_PAGE_LENGTH = 100
MAX_COMMITS = 100
MAX_COMPARE_EXAMPLES = 20

# A string column is shown as categories (value counts, filterable) when its
# values repeat and stay short: few distinct values, each a label.
CATEGORY_MAX_DISTINCT = 200
CATEGORY_MAX_VALUE_CHARS = 120
CATEGORY_TOP = 30
HISTOGRAM_BINS = 10


# --- errors -----------------------------------------------------------------


class HubNotFoundError(LookupError):
    """Unknown repo, revision, config or split, or one the token can't read."""


class HubTooLargeError(ValueError):
    """A split above ``config.max_hub_view_bytes``: too big to load in memory."""


class HubBadQueryError(ValueError):
    """A filter or sort that doesn't apply to the split's columns."""


class HubUnreadableError(ValueError):
    """Data files that can't be read as a table."""


class HubUnavailableError(RuntimeError):
    """The Hub failed to answer (network error, 5xx, rate limit)."""


def _hub_call(fn: Callable[[], T], not_found: str = "Dataset not found") -> T:
    """Run one Hub call, translating its errors into the viewer's own.

    A repo the token can't read answers like an unknown one: the Hub itself
    returns 404 for a private repo, and this keeps it that way.
    """
    from huggingface_hub.errors import (
        DisabledRepoError,
        EntryNotFoundError,
        GatedRepoError,
        HFValidationError,
        HfHubHTTPError,
        RepositoryNotFoundError,
        RevisionNotFoundError,
    )

    try:
        return fn()
    except GatedRepoError as exc:
        raise HubNotFoundError(
            "This dataset is gated and your token hasn't been granted access"
        ) from exc
    except (RepositoryNotFoundError, DisabledRepoError) as exc:
        raise HubNotFoundError(
            f"{not_found}, or your Hugging Face token can't read it"
        ) from exc
    except RevisionNotFoundError as exc:
        raise HubNotFoundError("Unknown revision") from exc
    except EntryNotFoundError as exc:
        raise HubNotFoundError("File not found at this revision") from exc
    except HFValidationError as exc:
        raise HubNotFoundError(f"{not_found}: invalid repo id or revision") from exc
    except (HfHubHTTPError, httpx.HTTPError, OSError) as exc:
        raise HubUnavailableError("The Hugging Face Hub request failed") from exc


# --- small LRU caches ----------------------------------------------------------


class _LRU:
    """Least-recently-used cache bounded by the total weight of its entries.

    ``budget`` is read on every insert, so a config change (or a test patching
    it) takes effect without rebuilding the cache. An entry heavier than the
    whole budget is simply not kept.
    """

    def __init__(self, budget: Callable[[], int], weigh: Callable[[Any], int]):
        self._budget = budget
        self._weigh = weigh
        self._entries: "OrderedDict[Hashable, Tuple[int, Any]]" = OrderedDict()
        self._total = 0
        self._lock = threading.Lock()

    def get(self, key: Hashable) -> Optional[Any]:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            self._entries.move_to_end(key)
            return entry[1]

    def put(self, key: Hashable, value: Any) -> None:
        weight = max(1, self._weigh(value))
        with self._lock:
            old = self._entries.pop(key, None)
            if old is not None:
                self._total -= old[0]
            budget = self._budget()
            if weight > budget:
                return
            self._entries[key] = (weight, value)
            self._total += weight
            while self._total > budget and self._entries:
                _, (evicted, _) = self._entries.popitem(last=False)
                self._total -= evicted

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._total = 0


_tables = _LRU(lambda: config.hub_cache_bytes, lambda table: table.nbytes)
# Small results: weighted by count rather than bytes.
_stats_cache = _LRU(lambda: 256, lambda _: 1)
_cards = _LRU(lambda: 256, lambda _: 1)
# (token fingerprint, repo, revision) -> (expires_at, Snapshot)
_resolved = _LRU(lambda: 1024, lambda _: 1)

# Two requests for the same uncached split download it once: the second waits
# on the first. Striped locks, so the map of locks never grows.
_LOAD_LOCKS = [threading.Lock() for _ in range(64)]


def _load_lock(key: Hashable) -> threading.Lock:
    return _LOAD_LOCKS[hash(key) % len(_LOAD_LOCKS)]


def clear_caches() -> None:
    """Forget every cached resolution, table, statistic and card (tests)."""
    for cache in (_tables, _stats_cache, _cards, _resolved):
        cache.clear()


# --- repo ids ----------------------------------------------------------------

# One segment of a repo id: what the Hub accepts, minus anything a path could
# be tricked with ("..", "/", leading dots).
_REPO_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")


def repo_id_of(owner: str, name: str) -> str:
    """``owner/name``, refusing anything that is not a plausible Hub repo id."""
    for part in (owner, name):
        if not _REPO_PART.match(part) or ".." in part or "--" in part:
            raise HubNotFoundError(f"'{owner}/{name}' is not a dataset repo id")
    return f"{owner}/{name}"


# --- listing -------------------------------------------------------------------


def _dataset_row(d: Any) -> Dict[str, Any]:
    """The listing fields of one Hub ``DatasetInfo``."""
    siblings = getattr(d, "siblings", None)
    return {
        "id": d.id,
        "url": f"https://huggingface.co/datasets/{d.id}",
        "author": getattr(d, "author", None),
        "private": bool(getattr(d, "private", False)),
        "gated": getattr(d, "gated", None) or False,
        "disabled": bool(getattr(d, "disabled", False)),
        "downloads": getattr(d, "downloads", None),
        "downloads_all_time": getattr(d, "downloads_all_time", None),
        "likes": getattr(d, "likes", None),
        "tags": list(getattr(d, "tags", None) or []),
        "description": getattr(d, "description", None),
        "file_count": len(siblings) if siblings is not None else None,
        "used_storage": getattr(d, "used_storage", None),
        "sha": getattr(d, "sha", None),
        "created_at": _json_safe(getattr(d, "created_at", None)),
        "last_modified": _json_safe(getattr(d, "last_modified", None)),
        **_card_metadata(getattr(d, "card_data", None)),
    }


def list_datasets(creds: Credentials, author: Optional[str] = None) -> Dict[str, Any]:
    """The dataset repos of one of the caller's namespaces, newest first.

    ``namespaces`` lists where the token can publish: the namespace saved in
    Settings, the token's own account and its organizations. ``author`` picks
    one of them (default: the saved namespace, else the account). Private
    repos are included: the listing is made with the caller's token.
    """
    _require_token(creds)
    api = _api(creds)
    me = _hub_call(lambda: api.whoami(cache=True), "Account not found")
    own = me.get("name") if isinstance(me, dict) else None
    orgs = [
        org.get("name")
        for org in ((me.get("orgs") if isinstance(me, dict) else None) or [])
        if isinstance(org, dict) and org.get("name")
    ]
    namespaces = list(dict.fromkeys(n for n in (creds.hf_namespace, own, *orgs) if n))
    target = author or creds.hf_namespace or own
    if not target:
        raise HuggingFaceNotConfiguredError(
            "Could not determine the Hugging Face namespace. Set your Hugging Face "
            "namespace in Settings (your user or organization name)."
        )
    if author and author not in namespaces:
        raise HubNotFoundError(f"'{author}' is not one of your Hugging Face namespaces")

    datasets = _hub_call(
        lambda: list(api.list_datasets(author=target, sort="last_modified", full=True)),
        "Namespace not found",
    )
    rows = [_dataset_row(d) for d in datasets]
    return {
        "namespace": target,
        "namespaces": namespaces,
        "total": len(rows),
        "datasets": rows,
    }


# --- resolving a revision ------------------------------------------------------


@dataclass(frozen=True)
class HubFile:
    path: str
    size: Optional[int]
    lfs: bool


@dataclass(frozen=True)
class Snapshot:
    """A repo at one commit, as the caller's token sees it."""

    repo_id: str
    sha: str
    info: Any
    files: Tuple[HubFile, ...]

    def size_of(self, path: str) -> Optional[int]:
        for f in self.files:
            if f.path == path:
                return f.size
        return None


def _fingerprint(creds: Credentials) -> str:
    """A stable, non-reversible key for the caller's token (cache keys only)."""
    return hashlib.sha256(creds.secret(HF_TOKEN).encode("utf-8")).hexdigest()[:32]


def _sibling_size(sibling: Any) -> Optional[int]:
    size = getattr(sibling, "size", None)
    if size is None and getattr(sibling, "lfs", None) is not None:
        size = getattr(sibling.lfs, "size", None)
    return int(size) if isinstance(size, (int, float)) else None


def resolve(
    creds: Credentials, repo_id: str, revision: Optional[str] = None
) -> Snapshot:
    """The repo at ``revision`` (default branch when None), read with the
    caller's token. Reused for a few seconds per token, see
    ``config.hub_resolve_ttl_seconds``."""
    _require_token(creds)
    key = (_fingerprint(creds), repo_id, revision or "")
    now = time.monotonic()
    hit = _resolved.get(key)
    if hit is not None and hit[0] > now:
        return hit[1]

    info = _hub_call(
        lambda: _api(creds).dataset_info(
            repo_id, revision=revision, files_metadata=True
        )
    )
    if not getattr(info, "sha", None):
        # Without a sha nothing can be pinned (or cached) safely.
        raise HubUnavailableError(
            "The Hugging Face Hub returned no commit for this revision"
        )
    files = tuple(
        HubFile(
            path=s.rfilename,
            size=_sibling_size(s),
            lfs=getattr(s, "lfs", None) is not None,
        )
        for s in (getattr(info, "siblings", None) or [])
    )
    snapshot = Snapshot(repo_id=repo_id, sha=str(info.sha), info=info, files=files)
    _resolved.put(key, (now + config.hub_resolve_ttl_seconds, snapshot))
    return snapshot


# --- configs and splits ----------------------------------------------------------


@dataclass(frozen=True)
class View:
    """One table of the dataset: a config's split, or an extra data file."""

    config: str
    split: str
    files: Tuple[str, ...]
    # A data file that belongs to no declared split (e.g. the app's
    # ``review.jsonl``), offered as its own table.
    extra: bool = False


# The Hub's split keywords: a keyword counts when it is a whole "word" of the
# path, separated by "/", "-", "_", ".", a space or a digit.
_SEP = r"[/\-._ 0-9]"
_SPLIT_KEYWORDS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("train", ("train", "training")),
    ("validation", ("validation", "valid", "dev", "val")),
    ("test", ("test", "testing", "eval", "evaluation")),
)
_SPLIT_PATTERNS = [
    (
        split,
        re.compile(rf"(?:^|{_SEP})(?:{'|'.join(words)})(?:{_SEP}|$)", re.IGNORECASE),
    )
    for split, words in _SPLIT_KEYWORDS
]


def _is_data_file(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    lower = name.lower()
    if any(part.startswith(".") for part in path.split("/")):
        return False
    if lower in _NON_DATA_FILENAMES or (path == name and lower in APP_STATE_FILES):
        return False
    return lower.endswith(DATA_EXTENSIONS)


def _format_of(path: str) -> str:
    lower = path.lower()
    if lower.endswith(".parquet"):
        return "parquet"
    if lower.endswith((".csv", ".tsv")):
        return "csv"
    return "json"


def _matches(path: str, patterns: Iterable[str]) -> bool:
    for pattern in patterns:
        pattern = pattern.lstrip("/")
        if fnmatch.fnmatchcase(path, pattern):
            return True
        # "**/x" also matches "x" at the root, as in the Hub's glob semantics.
        if pattern.startswith("**/") and fnmatch.fnmatchcase(path, pattern[3:]):
            return True
    return False


def _split_patterns(data_files: Any) -> List[Tuple[str, List[str]]]:
    """(split, patterns) pairs from a card config's ``data_files`` field, in
    any of the shapes the Hub accepts."""
    if isinstance(data_files, str):
        return [("train", [data_files])]
    if isinstance(data_files, dict):
        return [
            (str(split), [paths] if isinstance(paths, str) else [str(p) for p in paths])
            for split, paths in data_files.items()
            if isinstance(paths, (str, list))
        ]
    if isinstance(data_files, list):
        if all(isinstance(item, str) for item in data_files):
            return [("train", list(data_files))]
        pairs: List[Tuple[str, List[str]]] = []
        for item in data_files:
            if not isinstance(item, dict) or not item.get("path"):
                continue
            paths = item["path"]
            pairs.append(
                (
                    str(item.get("split") or "train"),
                    [paths] if isinstance(paths, str) else [str(p) for p in paths],
                )
            )
        return pairs
    return []


def _auto_views(config_name: str, data: List[str]) -> List[View]:
    """Splits by file and directory names, as the Hub does without a card
    ``configs`` block: train/validation/test keywords, else one train split of
    the most common format."""
    by_split: Dict[str, List[str]] = {}
    for path in data:
        for split, pattern in _SPLIT_PATTERNS:
            if pattern.search(path):
                by_split.setdefault(split, []).append(path)
                break
    if by_split:
        return [
            View(config_name, split, tuple(sorted(by_split[split])))
            for split, _ in _SPLIT_KEYWORDS
            if split in by_split
        ]
    if not data:
        return []
    groups: Dict[str, List[str]] = {}
    for path in data:
        groups.setdefault(_format_of(path), []).append(path)
    fmt = max(groups, key=lambda k: len(groups[k]))
    return [View(config_name, "train", tuple(sorted(groups[fmt])))]


def _card_configs(info: Any) -> List[Dict[str, Any]]:
    card = getattr(info, "card_data", None)
    if card is None:
        return []
    as_dict = card.to_dict() if hasattr(card, "to_dict") else dict(card)
    configs = as_dict.get("configs")
    return (
        [c for c in configs if isinstance(c, dict)] if isinstance(configs, list) else []
    )


def views(snapshot: Snapshot) -> List[View]:
    """Every table of the dataset at this commit, the default one first."""
    data = [f.path for f in snapshot.files if _is_data_file(f.path)]
    declared: List[View] = []
    configs = _card_configs(snapshot.info)
    if configs:
        # The default config first: flagged ``default``, else named "default".
        configs = sorted(
            configs,
            key=lambda c: (not c.get("default"), c.get("config_name") != "default"),
        )
        for cfg in configs:
            name = str(cfg.get("config_name") or "default")
            if cfg.get("data_files") is None and cfg.get("data_dir"):
                prefix = str(cfg["data_dir"]).strip("/") + "/"
                declared += _auto_views(name, [p for p in data if p.startswith(prefix)])
                continue
            for split, patterns in _split_patterns(cfg.get("data_files")):
                files = tuple(sorted(p for p in data if _matches(p, patterns)))
                if files:
                    declared.append(View(name, split, files))
    else:
        declared = _auto_views("default", data)

    used = {path for view in declared for path in view.files}
    taken = {(v.config, v.split) for v in declared}
    extra_config = declared[0].config if declared else "default"
    extras: List[View] = []
    for path in data:
        if path in used or not path.lower().endswith(EXTRA_EXTENSIONS):
            continue
        stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0] or path
        name = stem if (extra_config, stem) not in taken else path
        taken.add((extra_config, name))
        extras.append(View(extra_config, name, (path,), extra=True))
    return declared + extras


def find_view(
    snapshot: Snapshot, config_name: Optional[str], split: Optional[str]
) -> View:
    """The requested table, or the default one when neither is given."""
    available = views(snapshot)
    if not available:
        raise HubNotFoundError("This dataset has no data file the viewer can read")
    for view in available:
        if (config_name is None or view.config == config_name) and (
            split is None or view.split == split
        ):
            return view
    raise HubNotFoundError(
        f"No split '{split or '*'}' in config '{config_name or '*'}' at this revision"
    )


# --- reading a split ---------------------------------------------------------------


def _column_of(table: pa.Table, name: str) -> pa.Array:
    """One column as a single contiguous array."""
    column = table.column(name)
    if column.num_chunks == 1:
        return column.chunk(0)
    if column.num_chunks == 0:
        return pa.array([], type=column.type)
    return column.combine_chunks()


def _table_from_records(records: List[Any]) -> pa.Table:
    """Rows of any shape into a table, column by column.

    A column whose values don't share one type (a number in one row, a string
    in the next) is kept as JSON text rather than failing the whole split.
    """
    columns: Dict[str, List[Any]] = {}
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            record = {"value": record}
        for key in record:
            if str(key) not in columns:
                columns[str(key)] = [None] * index
        for key, values in columns.items():
            values.append(record.get(key))
    arrays: Dict[str, pa.Array] = {}
    for key, values in columns.items():
        try:
            arrays[key] = pa.array(values)
        except (pa.ArrowInvalid, pa.ArrowTypeError, OverflowError, ValueError):
            arrays[key] = pa.array(
                [
                    v
                    if v is None or isinstance(v, str)
                    else json.dumps(v, ensure_ascii=False, default=str)
                    for v in values
                ],
                type=pa.string(),
            )
    return pa.table(arrays) if arrays else pa.table({})


def _read_json_document(local: str) -> List[Any]:
    with open(local, encoding="utf-8-sig") as f:
        text = f.read()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # JSON Lines saved with a .json extension.
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # {"data": [...]} / {"train": [...]} wrappers.
        for value in data.values():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                return value
        return [data]
    return [data]


def _read_json_lines(local: str) -> List[Any]:
    with open(local, encoding="utf-8-sig") as f:
        return [json.loads(line) for line in f if line.strip()]


def _read_file(path: str, local: str) -> pa.Table:
    """One downloaded data file as a table."""
    import pyarrow.csv as pacsv
    import pyarrow.json as pajson
    import pyarrow.parquet as pq

    lower = path.lower()
    try:
        if lower.endswith(".parquet"):
            return pq.read_table(local)
        if lower.endswith((".csv", ".tsv")):
            delimiter = "\t" if lower.endswith(".tsv") else ","
            return pacsv.read_csv(
                local, parse_options=pacsv.ParseOptions(delimiter=delimiter)
            )
        if lower.endswith((".jsonl", ".ndjson")):
            try:
                return pajson.read_json(local)
            except (pa.ArrowInvalid, pa.ArrowTypeError):
                # Arrow infers each column's type from the first block and
                # refuses a later row that disagrees: fall back to a per-column
                # read that tolerates it.
                return _table_from_records(_read_json_lines(local))
        return _table_from_records(_read_json_document(local))
    except (pa.ArrowInvalid, pa.ArrowTypeError, ValueError, UnicodeDecodeError) as exc:
        raise HubUnreadableError(f"'{path}' could not be read as a table") from exc


def _concat(tables: List[pa.Table]) -> pa.Table:
    if not tables:
        return pa.table({})
    if len(tables) == 1:
        return tables[0]
    try:
        return pa.concat_tables(tables, promote_options="permissive")
    except (pa.ArrowInvalid, pa.ArrowTypeError):
        # Files whose columns can't be unified: rebuild from rows.
        return _table_from_records([row for t in tables for row in t.to_pylist()])


def _too_large(view: View) -> HubTooLargeError:
    limit = config.max_hub_view_bytes // (1024 * 1024)
    return HubTooLargeError(
        f"The '{view.split}' split is larger than the in-app viewer's {limit} MB "
        "limit. Open it on Hugging Face instead."
    )


def _download(creds: Credentials, snapshot: Snapshot, path: str, cache_dir: str) -> str:
    from huggingface_hub import hf_hub_download

    return _hub_call(
        lambda: hf_hub_download(
            repo_id=snapshot.repo_id,
            filename=path,
            repo_type="dataset",
            revision=snapshot.sha,
            token=creds.secret(HF_TOKEN),
            cache_dir=cache_dir,
        )
    )


def _read_view(creds: Credentials, snapshot: Snapshot, view: View) -> pa.Table:
    if len(view.files) > MAX_FILES_PER_SPLIT:
        raise _too_large(view)
    known = [snapshot.size_of(path) for path in view.files]
    if sum(size or 0 for size in known) > config.max_hub_view_bytes:
        raise _too_large(view)

    budget = config.max_hub_view_bytes
    tables: List[pa.Table] = []
    # A throwaway cache: the files are read once into the table, then deleted.
    with tempfile.TemporaryDirectory(prefix="hub-view-") as cache_dir:
        for path in view.files:
            local = _download(creds, snapshot, path, cache_dir)
            budget -= os.path.getsize(local)
            if budget < 0:
                raise _too_large(view)
            tables.append(_read_file(path, local))
    table = _concat(tables).combine_chunks()
    logger.info(
        "Hub viewer: loaded %s@%s %s/%s (%d rows, %d file(s))",
        snapshot.repo_id,
        snapshot.sha[:7],
        view.config,
        view.split,
        table.num_rows,
        len(view.files),
    )
    return table.append_column(
        ROW_IDX, pa.array(range(table.num_rows), type=pa.int64())
    )


def load_split(creds: Credentials, snapshot: Snapshot, view: View) -> pa.Table:
    """The split's table, from the cache or freshly downloaded.

    Only call with a ``snapshot`` from :func:`resolve` for the same ``creds``:
    that is what makes the shared cache safe across users.
    """
    key = (snapshot.repo_id, snapshot.sha, view.config, view.split)
    table = _tables.get(key)
    if table is not None:
        return table
    with _load_lock(key):
        table = _tables.get(key)
        if table is None:
            table = _read_view(creds, snapshot, view)
            _tables.put(key, table)
    return table


# --- columns ------------------------------------------------------------------------


def kind_of(dtype: pa.DataType) -> str:
    """The family of an Arrow type, as the UI groups them."""
    t = pa.types
    if t.is_string(dtype) or t.is_large_string(dtype) or t.is_string_view(dtype):
        return "string"
    if t.is_integer(dtype) or t.is_floating(dtype) or t.is_decimal(dtype):
        return "number"
    if t.is_boolean(dtype):
        return "bool"
    if (
        t.is_list(dtype)
        or t.is_large_list(dtype)
        or t.is_fixed_size_list(dtype)
        or t.is_list_view(dtype)
        or t.is_large_list_view(dtype)
    ):
        return "list"
    if t.is_struct(dtype) or t.is_map(dtype):
        return "object"
    if t.is_temporal(dtype):
        return "datetime"
    if t.is_binary(dtype) or t.is_large_binary(dtype) or t.is_fixed_size_binary(dtype):
        return "binary"
    if t.is_null(dtype):
        return "null"
    return "other"


def _features(table: pa.Table) -> List[Dict[str, str]]:
    return [
        {"name": f.name, "type": str(f.type), "kind": kind_of(f.type)}
        for f in table.schema
        if f.name != ROW_IDX
    ]


def qa_columns(table: pa.Table) -> Optional[Dict[str, Optional[str]]]:
    """The question/answer/context columns when the split is a Q/A dataset."""
    strings = {
        f.name.lower(): f.name
        for f in table.schema
        if f.name != ROW_IDX and kind_of(f.type) == "string"
    }

    def first(keys: Iterable[str]) -> Optional[str]:
        return next((strings[k] for k in keys if k in strings), None)

    question, answer = first(_QUESTION_KEYS), first(_ANSWER_KEYS)
    if not (question and answer):
        return None
    return {"question": question, "answer": answer, "context": first(_CONTEXT_KEYS)}


def jsonable(value: Any) -> Any:
    """An Arrow value converted to plain JSON (no NaN, dates as ISO text)."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date, time_of_day)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<{len(value)} bytes>"
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return str(value)


# --- search, filters, sort --------------------------------------------------------------

FILTER_OPS = ("eq", "ne", "lt", "lte", "gt", "gte", "contains", "null", "not_null")


@dataclass(frozen=True)
class RowFilter:
    column: str
    op: str
    value: Any = None


def _positions_mask(length: int, positions: pa.Array) -> pa.Array:
    """A boolean mask of ``length`` that is true at ``positions``."""
    value_set = pc.unique(pc.cast(positions, pa.int64()))
    return pc.is_in(pa.array(range(length), type=pa.int64()), value_set=value_set)


def _text_match(arr: pa.Array, query: str) -> Optional[pa.Array]:
    """Rows of ``arr`` with ``query`` in any of their text, nested included."""
    kind = kind_of(arr.type)
    if kind == "string":
        return pc.fill_null(pc.match_substring(arr, query, ignore_case=True), False)
    if pa.types.is_struct(arr.type):
        mask = None
        # flatten(), not field(i): it applies the struct's own offset and nulls.
        for field_values in arr.flatten():
            child = _text_match(field_values, query)
            if child is not None:
                mask = child if mask is None else pc.or_(mask, child)
        return mask
    if kind == "list" and not pa.types.is_fixed_size_list(arr.type):
        child = _text_match(arr.flatten(), query)
        if child is None:
            return None
        parents = pc.filter(pc.list_parent_indices(arr), child)
        return _positions_mask(len(arr), parents)
    return None


def _search_mask(table: pa.Table, query: str) -> pa.Array:
    mask = None
    for name in table.column_names:
        if name == ROW_IDX:
            continue
        match = _text_match(_column_of(table, name), query)
        if match is not None:
            mask = match if mask is None else pc.or_(mask, match)
    if mask is None:
        return pa.array([False] * table.num_rows, type=pa.bool_())
    return mask


def _coerce(value: Any, kind: str) -> Any:
    """A filter value as the column's type, or a clear error."""
    try:
        if kind == "number":
            if isinstance(value, bool):
                raise ValueError
            return float(value)
        if kind == "bool":
            if isinstance(value, bool):
                return value
            if str(value).lower() in ("true", "1", "yes"):
                return True
            if str(value).lower() in ("false", "0", "no"):
                return False
            raise ValueError
        if kind == "string":
            return str(value)
    except (TypeError, ValueError):
        raise HubBadQueryError(f"'{value}' is not a valid {kind} value")
    raise HubBadQueryError(f"Columns of type {kind} can't be filtered on a value")


_COMPARE = {
    "eq": pc.equal,
    "ne": pc.not_equal,
    "lt": pc.less,
    "lte": pc.less_equal,
    "gt": pc.greater,
    "gte": pc.greater_equal,
}


def _filter_mask(table: pa.Table, flt: RowFilter) -> pa.Array:
    if flt.column == ROW_IDX or flt.column not in table.column_names:
        raise HubBadQueryError(f"Unknown column '{flt.column}'")
    if flt.op not in FILTER_OPS:
        raise HubBadQueryError(f"Unknown filter operator '{flt.op}'")
    arr = _column_of(table, flt.column)
    kind = kind_of(arr.type)
    if flt.op == "null":
        return pc.is_null(arr)
    if flt.op == "not_null":
        return pc.is_valid(arr)
    if flt.op == "contains":
        if kind == "string":
            return pc.fill_null(
                pc.match_substring(arr, str(flt.value), ignore_case=True), False
            )
        if kind == "list" and not pa.types.is_fixed_size_list(arr.type):
            items = arr.flatten()
            hits = pc.fill_null(
                pc.equal(items, _coerce(flt.value, kind_of(items.type))), False
            )
            return _positions_mask(
                len(arr), pc.filter(pc.list_parent_indices(arr), hits)
            )
        raise HubBadQueryError(f"'contains' doesn't apply to column '{flt.column}'")
    if kind not in ("string", "number", "bool"):
        raise HubBadQueryError(f"Column '{flt.column}' can't be compared to a value")
    if kind == "bool" and flt.op not in ("eq", "ne"):
        raise HubBadQueryError(f"Column '{flt.column}' only supports eq and ne")
    return pc.fill_null(_COMPARE[flt.op](arr, _coerce(flt.value, kind)), False)


def _select(
    table: pa.Table,
    query: Optional[str],
    filters: Iterable[RowFilter],
    sort: Optional[str],
    order: str,
) -> pa.Table:
    mask = None
    if query and query.strip():
        mask = _search_mask(table, query.strip())
    for flt in filters:
        flt_mask = _filter_mask(table, flt)
        mask = flt_mask if mask is None else pc.and_(mask, flt_mask)
    selected = table.filter(mask) if mask is not None else table
    if sort:
        if sort == ROW_IDX or sort not in table.column_names:
            raise HubBadQueryError(f"Unknown column '{sort}'")
        if kind_of(table.schema.field(sort).type) not in (
            "string",
            "number",
            "bool",
            "datetime",
        ):
            raise HubBadQueryError(f"Column '{sort}' can't be sorted")
        direction = "descending" if order == "desc" else "ascending"
        selected = selected.sort_by([(sort, direction), (ROW_IDX, "ascending")])
    return selected


def _truncate(row: Dict[str, Any]) -> List[str]:
    """Cut long string cells in place; the names of the cut columns."""
    cut = []
    for key, value in row.items():
        if isinstance(value, str) and len(value) > MAX_CELL_CHARS:
            row[key] = value[:MAX_CELL_CHARS]
            cut.append(key)
    return cut


def _split_meta(snapshot: Snapshot, view: View) -> Dict[str, Any]:
    return {
        "repo_id": snapshot.repo_id,
        "sha": snapshot.sha,
        "config": view.config,
        "split": view.split,
    }


def rows(
    creds: Credentials,
    repo_id: str,
    *,
    revision: Optional[str] = None,
    config_name: Optional[str] = None,
    split: Optional[str] = None,
    offset: int = 0,
    length: int = 25,
    query: Optional[str] = None,
    filters: Iterable[RowFilter] = (),
    sort: Optional[str] = None,
    order: str = "asc",
) -> Dict[str, Any]:
    """One page of a split, after an optional search, filters and sort."""
    snapshot = resolve(creds, repo_id, revision)
    view = find_view(snapshot, config_name, split)
    table = load_split(creds, snapshot, view)
    selected = _select(table, query, list(filters), sort, order)
    length = max(1, min(length, MAX_PAGE_LENGTH))
    page = []
    for record in selected.slice(max(0, offset), length).to_pylist():
        row_idx = record.pop(ROW_IDX)
        row = jsonable(record)
        page.append({"row_idx": row_idx, "row": row, "truncated_cells": _truncate(row)})
    return {
        **_split_meta(snapshot, view),
        "features": _features(table),
        "qa": qa_columns(table),
        "rows": page,
        "num_rows_total": table.num_rows,
        "num_rows_matched": selected.num_rows,
        "offset": max(0, offset),
        "length": length,
    }


def row(
    creds: Credentials,
    repo_id: str,
    row_idx: int,
    *,
    revision: Optional[str] = None,
    config_name: Optional[str] = None,
    split: Optional[str] = None,
) -> Dict[str, Any]:
    """One full row (no cell cut), by its position in the split."""
    snapshot = resolve(creds, repo_id, revision)
    view = find_view(snapshot, config_name, split)
    table = load_split(creds, snapshot, view)
    if not 0 <= row_idx < table.num_rows:
        raise HubNotFoundError(f"No row {row_idx} in this split")
    record = table.slice(row_idx, 1).to_pylist()[0]
    record.pop(ROW_IDX)
    return {**_split_meta(snapshot, view), "row_idx": row_idx, "row": jsonable(record)}


# --- statistics ---------------------------------------------------------------------------


def _histogram(values: pa.Array) -> List[Dict[str, float]]:
    """Counts over equal-width bins; one bin per value for small integer ranges."""
    if len(values) == 0:
        return []
    bounds = pc.min_max(values).as_py()
    low, high = float(bounds["min"]), float(bounds["max"])
    if high == low:
        return [{"start": low, "end": high, "count": len(values)}]
    bins = HISTOGRAM_BINS
    width = (high - low) / bins
    if pa.types.is_integer(values.type) and high - low + 1 <= bins:
        bins, width = int(high - low + 1), 1.0
    floats = pc.cast(values, pa.float64())
    index = pc.cast(pc.floor(pc.divide(pc.subtract(floats, low), width)), pa.int64())
    index = pc.min_element_wise(index, bins - 1)
    counts = [0] * bins
    for entry in pc.value_counts(index).to_pylist():
        counts[entry["values"]] += entry["counts"]
    # Bin edges rounded to 6 significant digits: 0.58, not 0.5800000000000001.
    return [
        {
            "start": float(f"{low + i * width:.6g}"),
            "end": float(f"{low + (i + 1) * width:.6g}"),
            "count": counts[i],
        }
        for i in range(bins)
    ]


def _summary(values: pa.Array) -> Dict[str, Any]:
    """min/max/mean/median and a histogram of a numeric array without nulls."""
    if len(values) == 0:
        return {"min": None, "max": None, "mean": None, "median": None, "histogram": []}
    bounds = pc.min_max(values).as_py()
    return {
        "min": jsonable(bounds["min"]),
        "max": jsonable(bounds["max"]),
        "mean": jsonable(pc.mean(values).as_py()),
        "median": jsonable(pc.approximate_median(values).as_py()),
        "histogram": _histogram(values),
    }


def _categories(values: pa.Array) -> Optional[Dict[str, Any]]:
    """Value counts when the values look like labels (few, short, repeated)."""
    count = len(values)
    if count == 0:
        return None
    distinct = pc.count_distinct(values).as_py()
    # Labels repeat: a column of all-different values (questions, ids) is not
    # one, however short its values. Small tables get some slack (up to 10).
    if (
        distinct >= count
        or distinct > max(10, count // 2)
        or distinct > CATEGORY_MAX_DISTINCT
    ):
        return None
    if kind_of(values.type) == "string":
        longest = pc.max(pc.utf8_length(values)).as_py() or 0
        if longest > CATEGORY_MAX_VALUE_CHARS:
            return None
    counted = sorted(
        (
            (entry["values"], entry["counts"])
            for entry in pc.value_counts(values).to_pylist()
        ),
        key=lambda pair: (-pair[1], str(pair[0])),
    )
    top = counted[:CATEGORY_TOP]
    return {
        "distinct": distinct,
        "values": [{"value": jsonable(v), "count": c} for v, c in top],
        "other_count": sum(c for _, c in counted[CATEGORY_TOP:]),
    }


def _column_stats(name: str, arr: pa.Array) -> Dict[str, Any]:
    kind = kind_of(arr.type)
    valid = pc.drop_null(arr)
    stats: Dict[str, Any] = {
        "name": name,
        "type": str(arr.type),
        "kind": kind,
        "count": len(arr),
        "null_count": arr.null_count,
        # Character counts for strings, item counts for lists.
        "lengths": None,
        "number": None,
        "booleans": None,
        "categories": None,
    }
    if kind == "string":
        stats["lengths"] = _summary(pc.utf8_length(valid))
        stats["categories"] = _categories(valid)
    elif kind == "number":
        numbers = pc.cast(valid, pa.float64())
        # NaN is a value to Arrow, not a null: keep it out of min/max/bins.
        numbers = pc.filter(numbers, pc.invert(pc.is_nan(numbers)))
        stats["number"] = _summary(numbers)
    elif kind == "bool":
        true = int(pc.sum(pc.cast(valid, pa.int64())).as_py() or 0)
        stats["booleans"] = {"true": true, "false": len(valid) - true}
    elif kind == "list" and not pa.types.is_fixed_size_list(arr.type):
        stats["lengths"] = _summary(pc.list_value_length(valid))
        items = pc.drop_null(valid.flatten())
        if kind_of(items.type) in ("string", "number", "bool"):
            stats["categories"] = _categories(items)
    return stats


def _duplicates(table: pa.Table, column: str) -> Dict[str, Any]:
    """Rows whose ``column`` repeats an earlier row's, ignoring case and spaces."""
    values = pc.drop_null(_column_of(table, column))
    normalized = pc.utf8_lower(pc.utf8_trim_whitespace(values))
    repeated = sum(
        entry["counts"] - 1
        for entry in pc.value_counts(normalized).to_pylist()
        if entry["counts"] > 1
    )
    return {"column": column, "duplicate_rows": repeated}


def statistics(
    creds: Credentials,
    repo_id: str,
    *,
    revision: Optional[str] = None,
    config_name: Optional[str] = None,
    split: Optional[str] = None,
) -> Dict[str, Any]:
    """Per-column profile of a split: types, nulls, distributions, labels."""
    snapshot = resolve(creds, repo_id, revision)
    view = find_view(snapshot, config_name, split)
    key = (snapshot.repo_id, snapshot.sha, view.config, view.split)
    cached = _stats_cache.get(key)
    if cached is not None:
        return cached
    table = load_split(creds, snapshot, view)
    qa = qa_columns(table)
    question = qa["question"] if qa else None
    result = {
        **_split_meta(snapshot, view),
        "num_rows": table.num_rows,
        "num_columns": table.num_columns - 1,
        "columns": [
            _column_stats(name, _column_of(table, name))
            for name in table.column_names
            if name != ROW_IDX
        ],
        "qa": qa,
        "duplicates": _duplicates(table, question) if question else None,
    }
    _stats_cache.put(key, result)
    return result


# --- overview, card, history ---------------------------------------------------------------


def _strip_front_matter(text: str) -> str:
    """The card's Markdown body, without its YAML header."""
    if not text.startswith("---"):
        return text
    lines = text.split("\n")
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[index + 1 :]).lstrip("\n")
    return text


def _card(creds: Credentials, snapshot: Snapshot) -> Optional[str]:
    """The README body at this commit, or None without one."""
    path = next((f.path for f in snapshot.files if f.path.lower() == "readme.md"), None)
    if path is None or (snapshot.size_of(path) or 0) > MAX_CARD_BYTES:
        return None
    key = (snapshot.repo_id, snapshot.sha)
    cached = _cards.get(key)
    if cached is not None:
        return cached
    with tempfile.TemporaryDirectory(prefix="hub-card-") as cache_dir:
        local = _download(creds, snapshot, path, cache_dir)
        with open(local, encoding="utf-8", errors="replace") as f:
            body = _strip_front_matter(f.read(MAX_CARD_BYTES))
    _cards.put(key, body)
    return body


def _refs(creds: Credentials, repo_id: str) -> Dict[str, List[Dict[str, str]]]:
    """Branches and tags, best effort: the page still renders without them."""
    try:
        refs = _hub_call(
            lambda: _api(creds).list_repo_refs(repo_id, repo_type="dataset")
        )
    except HubUnavailableError:
        logger.warning("Hub viewer: could not list the refs of %s", repo_id)
        return {"branches": [], "tags": []}

    def entries(items: Any) -> List[Dict[str, str]]:
        return [
            {"name": ref.name, "target_commit": ref.target_commit}
            for ref in (items or [])
        ]

    return {"branches": entries(refs.branches), "tags": entries(refs.tags)}


def _view_bytes(snapshot: Snapshot, view: View) -> Optional[int]:
    """Total size of a table's files, None when one of them is unknown."""
    sizes = [snapshot.size_of(path) for path in view.files]
    return None if any(s is None for s in sizes) else sum(s or 0 for s in sizes)


def overview(
    creds: Credentials, repo_id: str, revision: Optional[str] = None
) -> Dict[str, Any]:
    """Everything the dataset page shows above its data: metadata, card,
    files, tables, refs."""
    snapshot = resolve(creds, repo_id, revision)
    info = snapshot.info
    card_data = getattr(info, "card_data", None)
    card_metadata = (
        card_data.to_dict() if hasattr(card_data, "to_dict") else dict(card_data or {})
    )
    tables = views(snapshot)
    return {
        **_dataset_row(info),
        "id": repo_id,
        "url": f"https://huggingface.co/datasets/{repo_id}",
        "sha": snapshot.sha,
        "revision": revision,
        "card": {
            "markdown": _card(creds, snapshot),
            "metadata": jsonable(card_metadata),
        },
        "files": [
            {"path": f.path, "size": f.size, "lfs": f.lfs} for f in snapshot.files
        ],
        "views": [
            {
                "config": v.config,
                "split": v.split,
                "files": list(v.files),
                "num_bytes": _view_bytes(snapshot, v),
                "extra": v.extra,
            }
            for v in tables
        ],
        "refs": _refs(creds, repo_id),
        "max_view_bytes": config.max_hub_view_bytes,
    }


def commits(creds: Credentials, repo_id: str) -> Dict[str, Any]:
    """The repo's history, newest first: every commit is a version."""
    _require_token(creds)
    history = _hub_call(
        lambda: _api(creds).list_repo_commits(repo_id, repo_type="dataset")
    )
    return {
        "repo_id": repo_id,
        "total": len(history),
        "commits": [
            {
                "id": c.commit_id,
                "title": c.title or "",
                "message": c.message or "",
                "authors": list(c.authors or []),
                "created_at": _json_safe(c.created_at),
            }
            for c in history[:MAX_COMMITS]
        ],
    }


# --- comparing two versions -----------------------------------------------------------------


def _row_key_column(base: pa.Table, head: pa.Table) -> Optional[str]:
    """``id`` when both versions carry it and it is unique in each."""
    for table in (base, head):
        if "id" not in table.column_names:
            return None
        ids = _column_of(table, "id")
        if kind_of(ids.type) not in ("string", "number") or ids.null_count:
            return None
        if pc.count_distinct(ids).as_py() != len(ids):
            return None
    return "id"


def _keyed(table: pa.Table, key: Optional[str]) -> Dict[Any, Dict[str, Any]]:
    keyed: Dict[Any, Dict[str, Any]] = {}
    for record in table.to_pylist():
        record.pop(ROW_IDX, None)
        record = jsonable(record)
        identity = (
            record[key]
            if key
            else hashlib.sha256(
                json.dumps(record, sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest()
        )
        keyed[identity] = record
    return keyed


def compare(
    creds: Credentials,
    repo_id: str,
    *,
    base: str,
    head: Optional[str] = None,
    config_name: Optional[str] = None,
    split: Optional[str] = None,
) -> Dict[str, Any]:
    """What changed in one split between two revisions, row by row.

    Rows are matched by their ``id`` column when both versions have a unique
    one (so an edited answer counts as *changed*), else by content (an edit is
    then a removal plus an addition).
    """
    head_snapshot = resolve(creds, repo_id, head)
    base_snapshot = resolve(creds, repo_id, base)
    head_view = find_view(head_snapshot, config_name, split)
    head_table = load_split(creds, head_snapshot, head_view)
    try:
        base_view = find_view(base_snapshot, head_view.config, head_view.split)
        base_table = load_split(creds, base_snapshot, base_view)
    except HubNotFoundError:
        # The split didn't exist yet at the base revision: everything is new.
        base_table = head_table.slice(0, 0)

    key = _row_key_column(base_table, head_table)
    before, after = _keyed(base_table, key), _keyed(head_table, key)
    added = [k for k in after if k not in before]
    removed = [k for k in before if k not in after]
    changed = [k for k in after if k in before and after[k] != before[k]]
    return {
        "repo_id": repo_id,
        "config": head_view.config,
        "split": head_view.split,
        "base": base_snapshot.sha,
        "head": head_snapshot.sha,
        "key": key or "content",
        "base_rows": base_table.num_rows,
        "head_rows": head_table.num_rows,
        "added": len(added),
        "removed": len(removed),
        "changed": len(changed),
        "unchanged": len(after) - len(added) - len(changed),
        "added_examples": [after[k] for k in added[:MAX_COMPARE_EXAMPLES]],
        "removed_examples": [before[k] for k in removed[:MAX_COMPARE_EXAMPLES]],
        "changed_examples": [
            {"before": before[k], "after": after[k]}
            for k in changed[:MAX_COMPARE_EXAMPLES]
        ],
    }
