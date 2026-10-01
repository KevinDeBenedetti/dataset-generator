"""Score existing Q/A pairs with an LLM judge.

Generation stores a ``confidence`` the model reports while writing each pair —
how well the source text supports the answer. Pairs that arrive another way (a
Hugging Face import, say) have none, so the quality page has no score to show.
This fills it in after the fact:

* with a context, the judge scores the same thing generation does — how well
  that context supports the answer;
* without one, it scores the pair on its own — a clear, specific question and
  an answer that addresses it directly and completely.

The two are not the same measurement, so each scored pair records
``confidence_method`` in its metadata.
"""

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional

from server.core.config import config
from server.services.datasets import get_pairs_to_score, set_pair_confidences
from server.services.model_defaults import resolve_model
from server.services.credentials import Credentials
from server.services.providers import (
    CompletionRequest,
    complete,
    get_provider,
    parse_ref,
)

logger = logging.getLogger(__name__)

BATCH_SIZE = 10
CONCURRENCY = 3
MAX_CONTEXT_CHARS = 1500

JUDGE_INSTRUCTION = """
You are a strict reviewer of question/answer pairs for a fine-tuning dataset.
For each numbered pair, output a confidence score between 0 and 1:

- When the pair has a Context: how well that context supports the answer.
- When it has none: how likely the pair is accurate and useful training data —
  a clear, specific question, and an answer that addresses it directly,
  completely and without vague or unverifiable claims.

Use the whole range: 0.9 and above is excellent, 0.7 to 0.9 is good with minor
issues, below 0.7 is flawed.

OUTPUT FORMAT (critical): the VERY LAST thing in your response must be a single
JSON object of this exact shape, with one entry per pair and nothing after it:
{"scores": [{"i": 1, "confidence": 0.85}]}
"""

_OBJECT = re.compile(r"\{[^{}]*\}")


class ScoringNotConfiguredError(RuntimeError):
    """Raised when the judge model's provider is not configured."""


def _format_batch(pairs: List[Dict[str, Any]]) -> str:
    blocks = []
    for i, pair in enumerate(pairs, start=1):
        block = f"[{i}]\nQ: {pair['question']}\nA: {pair['answer']}"
        context = (pair.get("context") or "").strip()
        if context:
            block += f"\nContext: {context[:MAX_CONTEXT_CHARS]}"
        blocks.append(block)
    return "\n\n".join(blocks)


def parse_scores(raw: str, count: int) -> Dict[int, float]:
    """``{1-based index: confidence}`` from the judge's reply.

    Scans for every flat ``{...}`` object instead of parsing one document, so a
    reply wrapped in prose or reasoning still yields its scores. Indexes out of
    range and unparseable values are dropped; scores are clamped to [0, 1].
    """
    scores: Dict[int, float] = {}
    for match in _OBJECT.finditer(raw):
        try:
            obj = json.loads(match.group(0))
            index = int(obj["i"])
            value = float(obj["confidence"])
        except (ValueError, KeyError, TypeError):
            continue
        if 1 <= index <= count:
            scores[index] = min(1.0, max(0.0, value))
    return scores


async def _score_batch(
    model: str, pairs: List[Dict[str, Any]], creds: Credentials
) -> Dict[str, float]:
    try:
        result = await complete(
            model,
            CompletionRequest(
                system=JUDGE_INSTRUCTION,
                user=_format_batch(pairs),
                max_tokens=config.max_tokens_qa,
                reasoning=True,
            ),
            creds,
        )
    except Exception as exc:
        logger.warning("scoring batch failed: %s", exc)
        return {}
    by_index = parse_scores(result.text, len(pairs))
    if len(by_index) < len(pairs):
        logger.warning("scoring batch returned %d/%d scores", len(by_index), len(pairs))
    return {pairs[i - 1]["id"]: score for i, score in by_index.items()}


async def score_dataset(
    owner_id: str,
    dataset_name: str,
    creds: Credentials,
    only_unscored: bool = True,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Score a dataset's pairs and store the results.

    ``model`` is a model reference (default: the qa role default). Raises
    ValueError for an unknown dataset and :class:`ScoringNotConfiguredError`
    when the judge's provider isn't configured.
    """
    model = resolve_model("qa", model, user_id=owner_id)
    provider = get_provider(parse_ref(model)[0]) if model else None
    if provider is None or not provider.configured(creds):
        missing = ", ".join(provider.missing(creds)) if provider else "a qa model"
        raise ScoringNotConfiguredError(
            f"No judge model is usable — add {missing} in Settings to score Q/A pairs."
        )
    pairs = await asyncio.to_thread(
        get_pairs_to_score, owner_id, dataset_name, only_unscored
    )

    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def run(batch: List[Dict[str, Any]]) -> Dict[str, float]:
        async with semaphore:
            return await _score_batch(model, batch, creds)

    batches = [pairs[i : i + BATCH_SIZE] for i in range(0, len(pairs), BATCH_SIZE)]
    scores: Dict[str, float] = {}
    for result in await asyncio.gather(*(run(b) for b in batches)):
        scores.update(result)

    updated = await asyncio.to_thread(
        set_pair_confidences, owner_id, dataset_name, scores, f"llm_judge:{model}"
    )
    logger.info(
        "scored %d/%d pair(s) of %r with %s", updated, len(pairs), dataset_name, model
    )
    return {
        "dataset_name": dataset_name,
        "model": model,
        "requested": len(pairs),
        "scored": updated,
        "failed": len(pairs) - updated,
    }
