"""The duplicate check of a dataset or a draft (services/similarity.py
``similar_pairs``): pre-filtered, and still finding exactly what the plain
comparison of every pair finds."""

import random
from difflib import SequenceMatcher

from server.services import similarity
from server.services.similarity import ANSWER_SIMILARITY_FLOOR, similar_pairs

TOPICS = ["the build", "the release", "the worker", "a dataset", "the Hub token"]
SHAPES = [
    "What is the purpose of {}?",
    "How does {} work in this project?",
    "Why would someone change {}?",
    "Where is {} configured, and by whom?",
]


def _pairs(count: int, seed: int = 7):
    """Templated questions with a few rewordings: some real repeats, many
    look-alikes about different things, most unrelated."""
    rng = random.Random(seed)  # noqa: S311 — test data
    pairs = []
    for i in range(count):
        topic, shape = rng.choice(TOPICS), rng.choice(SHAPES)
        question = shape.format(topic)
        if rng.random() < 0.3:
            question = question.replace("What is", "What's").replace("?", " exactly?")
        answer = f"It concerns {topic}: " + " ".join(
            rng.choice(["fast", "safe", "private", "daily", "manual", "shared"])
            for _ in range(rng.randint(3, 9))
        )
        pairs.append({"id": str(i), "question": question, "answer": answer})
    return pairs


def _plain(pairs, threshold):
    """Every pair compared in full: what the check did before the pre-filter."""
    for i, a in enumerate(pairs):
        for j in range(i + 1, len(pairs)):
            b = pairs[j]
            ratio = SequenceMatcher(None, a["question"], b["question"]).ratio()
            if ratio < threshold:
                continue
            if (
                SequenceMatcher(None, a["answer"], b["answer"]).ratio()
                >= ANSWER_SIMILARITY_FLOOR
            ):
                yield i, j, ratio


def test_the_pre_filter_changes_nothing_that_is_found():
    pairs = _pairs(120)
    for threshold in (0.6, 0.8, 0.95):
        found = list(similar_pairs(pairs, threshold))
        assert found == list(_plain(pairs, threshold))
    assert list(similar_pairs(pairs, 0.8)), "the sample holds no duplicate at all"


def test_most_pairs_never_reach_the_full_comparison(monkeypatch):
    pairs = [
        {"id": "a", "question": "What is the purpose of the build?", "answer": "A."},
        {"id": "b", "question": "Who?", "answer": "B."},  # far shorter
        {"id": "c", "question": "zzzz qqqq xxxx jjjj vvvv kkkk wwww", "answer": "C."},
        {"id": "d", "question": "What is the purpose of the build ?", "answer": "A."},
    ]
    full = []

    class Counting(SequenceMatcher):
        def __init__(self, isjunk, a: str, b: str) -> None:
            super().__init__(isjunk, a, b)
            self.first = a

        def ratio(self) -> float:
            full.append(self.first)
            return super().ratio()

    monkeypatch.setattr(similarity, "SequenceMatcher", Counting)

    assert [(i, j) for i, j, _ in similar_pairs(pairs, 0.8)] == [(0, 3)]
    # Six pairs of questions; only the look-alike is matched in full, then its answers.
    assert full == ["What is the purpose of the build?", "A."]


def test_no_pairs_and_one_pair_have_nothing_to_compare():
    assert list(similar_pairs([], 0.8)) == []
    assert list(similar_pairs(_pairs(1), 0.8)) == []
