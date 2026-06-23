"""Root pytest configuration.

Excludes environment-secret files from collection. pytest's directory walk
calls ``pytest_ignore_collect`` → ``Path.is_dir()`` on every sibling of the
test paths, including the repo-root ``.env`` / ``.env.example``. The dev
sandbox denies ``stat`` on those files, which crashes collection before any
test runs. ``collect_ignore_glob`` is checked *before* that ``is_dir()`` call
(see ``_pytest/main.py:pytest_ignore_collect``), so matching the env files here
short-circuits the stat and lets the suite collect in-sandbox.
"""

collect_ignore_glob = ["*.env", ".env", ".env.*"]
