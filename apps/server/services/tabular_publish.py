"""Publishing an approved tabular draft as the next version of its Hub dataset
repo (ADR 0005, 0006).

One commit: the draft's Parquet in shards of at most ``SHARD_BYTES`` (the Hub's
viewer reads them without conversion), the app card and the manifest. A
public dataset needs a licence that allows redistribution
(hub/licences.py); everything else stays private, and the repo safety rules
(moved dataset, private repo, a repo the app didn't make) are
services/hub_repo.py's.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from server.hub.card import tabular_card
from server.hub.licences import public_refusal
from server.hub.provenance import data_paths, manifest, manifest_bytes
from server.models.data_source import Publication, Recipe
from server.models.job_run import JobRun
from server.services.credentials import Credentials

logger = logging.getLogger(__name__)

# The largest Parquet file of a publication.
SHARD_BYTES = 500 * 1024 * 1024


class PublishRefused(ValueError):
    """The draft can't be published as asked: the message says why."""


def public_allowed(draft: Dict[str, Any]) -> Optional[str]:
    """Why ``draft`` can't be public (its licence), or None when it can."""
    return public_refusal((draft.get("provenance") or {}).get("licence"))


def _shards(run_dir: Path, data: Path) -> List[Path]:
    """``data`` as shards of at most ``SHARD_BYTES`` (itself when small)."""
    if data.stat().st_size <= SHARD_BYTES:
        return [data]
    from server.engine.profile import split_parquet
    from server.engine.session import session

    with session(run_dir) as s:
        return split_parquet(s, data, run_dir / "shards", SHARD_BYTES // 2)


def publish_draft(
    db: Session,
    creds: Credentials,
    owner_id: str,
    run_id: str,
    draft: Dict[str, Any],
    *,
    message: Optional[str] = None,
    backend: Any = None,
) -> Dict[str, Any]:
    """Publish ``draft`` (run ``run_id``'s); records the ``publications`` row.
    The caller marks the run."""
    from server.services.draft_store import get_store
    from server.services.hub_repo import open_repo

    public = draft.get("visibility") == "public"
    if public:
        refusal = public_allowed(draft)
        if refusal:
            raise PublishRefused(refusal)
    store = get_store()
    run_dir = store.run_dir(owner_id, run_id)
    data = run_dir / "data.parquet"
    if not data.is_file():
        raise PublishRefused("The draft's rows are gone: run the recipe again")
    target = str(draft.get("target_repo") or "")
    if not target:
        raise PublishRefused("The recipe names no Hugging Face repo")
    repo = open_repo(creds, target, backend=backend)
    shards = _shards(run_dir, data)
    paths = data_paths(len(shards))
    files = dict(zip(paths, shards, strict=True))
    card = tabular_card(repo.repo_id, draft)
    body = manifest_bytes(manifest(draft, run_id, files))
    rows = draft.get("rows", 0)
    published = repo.publish_table(
        files,
        card=card,
        manifest=body,
        message=message or f"Publish {rows} rows (run {run_id})",
        public=public,
    )
    recipe_id = draft.get("recipe_id")
    if recipe_id and db.get(Recipe, recipe_id) is None:
        recipe_id = None  # deleted since the run
    db.add(
        Publication(
            owner_id=owner_id,
            run_id=run_id,
            recipe_id=recipe_id,
            repo_id=published["repo_id"],
            commit_sha=published["commit"],
            visibility=published["visibility"],
            published_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
    return published


def publish(
    db: Session,
    creds: Credentials,
    run: JobRun,
    *,
    backend: Any = None,
) -> Dict[str, Any]:
    """Publish ``run``'s draft and mark the run published; the publication
    (repo, commit, url, visibility).

    Raises :class:`PublishRefused` and the Hub repo's own errors
    (:class:`~server.services.hub_repo.HubRepoError`)."""
    published = publish_draft(
        db, creds, run.owner_id, run.id, run.draft or {}, backend=backend
    )
    run.status = "published"
    run.published_url = published["url"]
    run.published_at = datetime.now(timezone.utc)
    db.commit()
    return published
