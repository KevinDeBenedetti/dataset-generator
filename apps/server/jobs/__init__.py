"""Batch jobs that publish datasets to the Hugging Face Hub.

Run from ``apps/``, e.g. ``uv run python -m server.jobs.corpus export``; the
scheduled GitHub workflows (``.github/workflows/*-sync.yml``) call them.
"""
