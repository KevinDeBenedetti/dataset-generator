"""Near-duplicate Q&A pairs: the check a draft's review and a dataset's
analysis share (services/draft_quality.py, services/datasets.py).

Plain text comparison, no model: two pairs are near-duplicates when their
questions read almost the same and their answers do too. Kept apart from the
local datasets module, which the draft review must outlive.
"""

from collections import Counter
from difflib import SequenceMatcher
from typing import Any, Dict, Iterator, List, Tuple


# A near-identical question alone is not a duplicate: templated questions
# ("What is the purpose of the X repository?") differ by one entity and score
# 0.9+ while being about different things. Their answers give it away (~0.2–0.4
# on real data), whereas a genuine repeat restates the same answer. Same idea
# as the context floor dedup applies at generation time (services.dedup).
ANSWER_SIMILARITY_FLOOR = 0.5


def may_reach(a: str, a_chars: Counter, b: str, b_chars: Counter, floor: float) -> bool:
    """Whether ``SequenceMatcher(None, a, b).ratio()`` can reach ``floor``.

    Its two upper bounds, as difflib's ``real_quick_ratio`` and ``quick_ratio``
    compute them — the lengths, then the characters the texts share — from
    counts made once per text instead of once per comparison.
    """
    total = len(a) + len(b)
    if not total:
        return True  # two empty texts: the ratio is 1.0
    if 2.0 * min(len(a), len(b)) / total < floor:
        return False
    return 2.0 * sum((a_chars & b_chars).values()) / total >= floor


def similar_pairs(
    pairs: List[Dict[str, Any]], threshold: float
) -> Iterator[Tuple[int, int, float]]:
    """Yield (i, j, ratio) for pairs whose questions reach the threshold and
    whose answers reach :data:`ANSWER_SIMILARITY_FLOOR`.

    Most pairs are ruled out by :func:`may_reach` before the quadratic
    matching: a 400-pair draft is 80,000 comparisons.
    """
    questions = [Counter(p["question"]) for p in pairs]
    answers = [Counter(p["answer"]) for p in pairs]
    for i, a in enumerate(pairs):
        for j in range(i + 1, len(pairs)):
            b = pairs[j]
            if not may_reach(
                a["question"], questions[i], b["question"], questions[j], threshold
            ):
                continue
            ratio = SequenceMatcher(None, a["question"], b["question"]).ratio()
            if ratio < threshold:
                continue
            if not may_reach(
                a["answer"],
                answers[i],
                b["answer"],
                answers[j],
                ANSWER_SIMILARITY_FLOOR,
            ):
                continue
            answer_ratio = SequenceMatcher(None, a["answer"], b["answer"]).ratio()
            if answer_ratio >= ANSWER_SIMILARITY_FLOOR:
                yield i, j, ratio
