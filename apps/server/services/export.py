"""``GET /me/export``: everything a user owns, as a zip — never their secrets.

* ``account.json`` — email, role, dates, linked sign-in providers;
* ``settings.json`` — integration settings, model defaults, quality rules,
  and *which* keys are saved (not their values);
* ``datasets/<name>.jsonl`` — every Q/A pair of each dataset.
"""

import io
import json
import re
import zipfile
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from server.models.user import User
from server.services.datasets import get_dataset_pairs, list_datasets_view
from server.services.identities import list_identities
from server.services.model_defaults import get_model_defaults
from server.services.quality_rules import get_quality_rules
from server.services.user_secrets import get_settings, secret_statuses


def _json(value: Any) -> str:
    def default(v: Any) -> Any:
        if isinstance(v, (datetime, date)):
            return v.isoformat()
        return str(v)

    return json.dumps(value, indent=2, ensure_ascii=False, default=default)


def _filename(name: str, taken: set) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.") or "dataset"
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}-{n}", n + 1
    taken.add(candidate)
    return candidate


def build_export(db: Session, user: User) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "account.json",
            _json(
                {
                    "email": user.email,
                    "role": user.role,
                    "created_at": user.created_at,
                    "last_login_at": user.last_login_at,
                    "sign_in": [
                        {"provider": i["provider"], "username": i["username"]}
                        for i in list_identities(db, user)
                    ],
                }
            ),
        )
        archive.writestr(
            "settings.json",
            _json(
                {
                    "integrations": get_settings(user.id),
                    "keys_saved": sorted(
                        k
                        for k, s in secret_statuses(user.id).items()
                        if s["configured"]
                    ),
                    "model_defaults": get_model_defaults(user.id),
                    "quality_rules": get_quality_rules(user.id),
                }
            ),
        )
        taken: set = set()
        for dataset in list_datasets_view(user.id):
            pairs = get_dataset_pairs(user.id, dataset["name"])
            lines = "\n".join(
                json.dumps(p, ensure_ascii=False, default=str) for p in pairs
            )
            archive.writestr(
                f"datasets/{_filename(dataset['name'], taken)}.jsonl",
                lines + ("\n" if lines else ""),
            )
    return buffer.getvalue()
