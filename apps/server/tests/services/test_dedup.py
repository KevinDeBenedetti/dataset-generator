"""Unit tests for the pure QA duplicate-detection core (no DB)."""

from server.services.dedup import (
    CONTEXT_SIMILARITY_FLOOR,
    QAEntry,
    classify_duplicate,
    find_similar,
)


def _entry(hash="h", question="q", context="c", source_url="https://example.com"):
    return QAEntry(hash=hash, question=question, context=context, source_url=source_url)


class TestClassifyDuplicate:
    def test_empty_existing_is_new(self):
        verdict = classify_duplicate(_entry(), [])
        assert verdict.type == "new"
        assert verdict.duplicate_hash is None
        assert verdict.similarity_score == 0.0

    def test_exact_hash_match(self):
        existing = [_entry(hash="abc", question="totally different question")]
        candidate = _entry(hash="abc", question="unrelated wording")
        verdict = classify_duplicate(candidate, existing)
        assert verdict.type == "exact"
        assert verdict.duplicate_hash == "abc"
        assert verdict.similarity_score == 1.0

    def test_exact_wins_over_similar(self):
        # One entry is an exact-hash match, another is a near-similar match;
        # exact must be reported.
        existing = [
            _entry(hash="similar", question="What is Python?", context="ctx"),
            _entry(hash="exact", question="totally unrelated", context="zzz"),
        ]
        candidate = _entry(hash="exact", question="What is Python?", context="ctx")
        verdict = classify_duplicate(candidate, existing)
        assert verdict.type == "exact"
        assert verdict.duplicate_hash == "exact"

    def test_similar_match_same_source(self):
        existing = [
            _entry(
                hash="e1", question="What is Python?", context="Python is a language"
            )
        ]
        candidate = _entry(
            hash="e2", question="What is Python???", context="Python is a language"
        )
        verdict = classify_duplicate(candidate, existing, similarity_threshold=0.9)
        assert verdict.type == "similar"
        assert verdict.duplicate_hash == "e1"
        assert 0.9 <= verdict.similarity_score < 1.0

    def test_different_source_url_is_new(self):
        existing = [
            _entry(
                hash="e1",
                question="What is Python?",
                context="Python is a language",
                source_url="https://a.com",
            )
        ]
        candidate = _entry(
            hash="e2",
            question="What is Python?",
            context="Python is a language",
            source_url="https://b.com",
        )
        assert classify_duplicate(candidate, existing).type == "new"

    def test_question_below_threshold_is_new(self):
        existing = [
            _entry(hash="e1", question="What is Python?", context="same context")
        ]
        candidate = _entry(
            hash="e2",
            question="How do I bake sourdough bread at home?",
            context="same context",
        )
        assert (
            classify_duplicate(candidate, existing, similarity_threshold=0.9).type
            == "new"
        )

    def test_context_below_floor_is_new(self):
        # Identical question, but the context is entirely different, so the
        # context floor keeps it out of "similar".
        existing = [
            _entry(hash="e1", question="What is Python?", context="A snake species.")
        ]
        candidate = _entry(
            hash="e2",
            question="What is Python?",
            context="A high-level programming language used for data science.",
        )
        assert classify_duplicate(candidate, existing).type == "new"

    def test_threshold_is_honoured(self):
        existing = [_entry(hash="e1", question="colour", context="ctx")]
        candidate = _entry(hash="e2", question="color", context="ctx")
        # A lenient threshold treats the near-identical questions as similar...
        assert classify_duplicate(
            candidate, existing, similarity_threshold=0.5
        ).type == ("similar")
        # ...while a strict threshold keeps them distinct.
        assert (
            classify_duplicate(candidate, existing, similarity_threshold=0.99).type
            == "new"
        )


class TestFindSimilar:
    def test_returns_first_match_in_order(self):
        existing = [
            _entry(hash="first", question="What is Python?", context="ctx"),
            _entry(hash="second", question="What is Python?", context="ctx"),
        ]
        candidate = _entry(hash="c", question="What is Python?", context="ctx")
        match = find_similar(candidate, existing, threshold=0.9)
        assert match is not None
        assert match[0] == "first"

    def test_no_match_returns_none(self):
        existing = [_entry(hash="e1", question="apples", context="ctx")]
        candidate = _entry(hash="c", question="quantum chromodynamics", context="ctx")
        assert find_similar(candidate, existing, threshold=0.9) is None

    def test_skips_other_sources(self):
        existing = [
            _entry(
                hash="e1", question="same", context="ctx", source_url="https://a.com"
            )
        ]
        candidate = _entry(
            hash="c", question="same", context="ctx", source_url="https://b.com"
        )
        assert find_similar(candidate, existing) is None

    def test_context_floor_constant(self):
        # Guard the documented floor so a change is a conscious decision.
        assert CONTEXT_SIMILARITY_FLOOR == 0.95
