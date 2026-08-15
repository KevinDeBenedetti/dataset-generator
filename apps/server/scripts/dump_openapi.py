"""Dump the FastAPI OpenAPI schema to a file, without starting a server.

Usage (from the repo root):

    uv run python -m server.scripts.dump_openapi [OUTPUT]

OUTPUT defaults to ``openapi.json``. This is what lets CI check the committed
TypeScript client against the current API: ``make api-client`` normally scrapes
a running server, which a CI job has no reason to boot.

Importing ``server.main`` builds the app (and therefore validates the config),
so placeholder values are injected for the few env vars that are required at
import time but irrelevant to the schema.
"""

import json
import os
import sys

# Must happen before importing the app: server.core.config validates on import
# and raises when OPENAI_API_KEY is missing.
os.environ.setdefault("OPENAI_API_KEY", "schema-dump-placeholder")
os.environ.setdefault("OPENAI_BASE_URL", "https://api.openai.com/v1")
os.environ.setdefault("OPENAI_LLM_MODEL", "gpt-4o-mini")
os.environ.setdefault("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
os.environ.setdefault("OPENAI_VLM_MODEL", "gpt-4o-mini")
# The dev log console mounts an extra router; keep it out of the schema so the
# generated client doesn't depend on how the dumping machine is configured.
os.environ["DEBUG_LOGS"] = ""

from server.main import app  # noqa: E402


def main() -> None:
    output = sys.argv[1] if len(sys.argv) > 1 else "openapi.json"
    schema = app.openapi()
    with open(output, "w", encoding="utf-8") as fh:
        # Keys are written in the app's own order, NOT sorted: the client
        # generator emits operations in schema order, so sorting here would make
        # the generated client differ from one built against the live server —
        # a diff no amount of regenerating could settle.
        json.dump(schema, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"OpenAPI schema written to {output} ({len(schema.get('paths', {}))} paths)")


if __name__ == "__main__":
    main()
