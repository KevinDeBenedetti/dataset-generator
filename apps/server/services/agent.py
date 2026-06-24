"""QA generation agent.

Calls the configured OpenAI-compatible endpoint directly (same client family as
``LLMService``), instructing the model to emit a JSON list of QA pairs which we
parse tolerantly. No agent framework / LiteLLM layer is involved, so provider
params (e.g. ``reasoning_effort`` for gpt-oss models) are forwarded verbatim.
"""

import json
import logging
import re
from collections import Counter
from typing import List, Optional

import openai
from pydantic import BaseModel, ValidationError

from server.core.config import config
from server.schemas.dataset import QA


class QAList(BaseModel):
    """Container model so the model can return a structured list of pairs."""

    items: List[QA]


QA_AGENT_INSTRUCTION = """
You are an expert dataset builder. From the source text the user provides,
generate high-quality question-answer pairs for a fine-tuning dataset.

Strict rules:
- Varied questions (what, who, when, where, why, how), each ending with "?"
- Complete, precise answers of at least 2 sentences (minimum 20 characters)
- The "context" field must be the exact excerpt from the source text that
  supports the answer (at least 50 characters)
- A "confidence" score between 0 and 1 reflecting how well the source supports
  the answer
- Avoid trivial or overly generic questions
- Questions and answers must be written in the requested target language

OUTPUT FORMAT (critical):
Prefer to respond with RAW JSON ONLY — no markdown, no code fences. If you must
reason first, keep it short; the VERY LAST thing in your response MUST be a
single JSON object of this exact shape, with nothing after the closing brace:
{"items": [{"question": "...", "answer": "...", "context": "...", "confidence": 0.9}]}
"""


def _coerce_items(raw_items: list) -> List[QA]:
    """Validate each candidate item, skipping (not failing on) invalid ones.

    Keeps the good pairs when the model emits one that violates the schema
    (e.g. a context shorter than the 50-char minimum) instead of discarding the
    whole batch. Boilerplate-heavy pages (nav menus, section headings) make the
    model emit many short fragments, so skips are summarised in a single INFO
    line (count + per-field/reason breakdown) rather than one warning per item.
    """
    items: List[QA] = []
    reasons: Counter = Counter()
    skipped = 0
    for item in raw_items:
        try:
            items.append(QA.model_validate(item))
        except ValidationError as exc:
            skipped += 1
            for err in exc.errors():
                field = ".".join(str(p) for p in err.get("loc", ())) or "?"
                reasons[f"{field}: {err.get('type', 'invalid')}"] += 1
        except Exception:
            skipped += 1
            reasons["unparseable"] += 1

    if skipped:
        breakdown = ", ".join(f"{reason} ×{n}" for reason, n in reasons.most_common())
        logging.info(
            "Skipped %d/%d QA item(s) failing validation (%s)",
            skipped,
            len(raw_items),
            breakdown,
        )
    return items


def _truncate_for_log(text: str, head: int = 220, tail: int = 220) -> str:
    """Single-line, length-capped view of a model response for diagnostics."""
    flat = " ".join(text.split())
    if len(flat) <= head + tail:
        return flat
    omitted = len(flat) - head - tail
    return f"{flat[:head]} … [{omitted} chars omitted] … {flat[-tail:]}"


def _parse_qa_list(text: str) -> List[QA]:
    """Parse the model's response into a list of QA pairs.

    Tolerant of empty responses, markdown code fences, a bare JSON array, a
    ``{"items": [...]}`` object, or JSON embedded in surrounding prose, and of
    individual items that fail validation. Returns an empty list rather than
    raising when nothing parseable is found.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.S).strip()
    if not cleaned:
        return []

    # Fast path: the whole payload is a QAList object with all-valid items.
    try:
        return QAList.model_validate_json(cleaned).items
    except Exception:
        pass

    # Otherwise locate the first JSON array or object, even if wrapped in prose.
    raw_items: list = []
    for open_ch, close_ch in (("[", "]"), ("{", "}")):
        start = cleaned.find(open_ch)
        end = cleaned.rfind(close_ch)
        if start == -1 or end == -1 or end <= start:
            continue
        try:
            data = json.loads(cleaned[start : end + 1])
        except Exception:
            continue
        if isinstance(data, list):
            raw_items = data
        elif isinstance(data, dict):
            raw_items = data["items"] if isinstance(data.get("items"), list) else [data]
        if raw_items:
            break

    # Salvage path: reasoning models or a hit token budget (max_tokens_qa) can
    # cut the response off mid-array, leaving the outer JSON unparseable. Recover
    # every complete flat object so a truncated response still yields its pairs.
    if not raw_items:
        for obj in re.findall(r"\{[^{}]*\}", cleaned):
            try:
                raw_items.append(json.loads(obj))
            except Exception:
                continue

    if not raw_items:
        logging.warning(
            "QA model response could not be parsed as QA pairs — no JSON found. "
            "Raw response: %s",
            _truncate_for_log(cleaned),
        )
        return []

    items = _coerce_items(raw_items)
    if not items:
        logging.warning(
            "QA model returned %d candidate item(s) but none passed validation "
            "(see skip summary). Raw response: %s",
            len(raw_items),
            _truncate_for_log(cleaned),
        )
    return items


class QAAgentService:
    """Generate QA pairs by calling the configured model over the OpenAI SDK."""

    def __init__(self):
        self.client = openai.AsyncOpenAI(
            api_key=config.openai_api_key,
            base_url=config.openai_base_url or None,
        )

    async def _run(self, text: str, target_language: str, model: str) -> str:
        """Call the model once and return its raw response text."""
        # reasoning_effort goes through extra_body so it reaches the endpoint
        # verbatim. "low" keeps gpt-oss-style models from spending their whole
        # budget reasoning and never emitting the final JSON.
        extra_body = {}
        if config.openai_reasoning_effort:
            extra_body["reasoning_effort"] = config.openai_reasoning_effort

        prompt = f"Target language: {target_language}\n\nSource text:\n{text}"
        response = await self.client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": QA_AGENT_INSTRUCTION},
                {"role": "user", "content": prompt},
            ],
            max_tokens=config.max_tokens_qa,
            temperature=config.temperature,
            extra_body=extra_body or None,
        )
        return (response.choices[0].message.content or "").strip()

    async def generate_qa(
        self,
        text: str,
        target_language: Optional[str] = None,
        model: Optional[str] = None,
    ) -> List[QA]:
        """Generate QA pairs; returns an empty list on failure."""
        target_language = target_language or config.target_language or "en"
        model = model or config.model_qa
        try:
            raw = await self._run(text, target_language, model)
            if not raw:
                logging.error("QA model returned no content")
                return []
            return _parse_qa_list(raw)
        except Exception:
            logging.exception("QA generation failed")
            return []

    async def generate_qa_debug(
        self,
        text: str,
        target_language: Optional[str] = None,
        model: Optional[str] = None,
    ) -> dict:
        """Run the model and return diagnostics (raw response + parsed pairs).

        Used by the QA verification page to inspect exactly what the model
        returns and whether it parses into valid QA pairs.
        """
        target_language = target_language or config.target_language or "en"
        model = model or config.model_qa
        raw_response = ""
        error: Optional[str] = None
        pairs: List[QA] = []
        try:
            raw_response = await self._run(text, target_language, model)
            pairs = _parse_qa_list(raw_response)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            logging.exception("QA agent debug run failed")

        return {
            "model": model,
            "target_language": target_language,
            "raw_response": raw_response,
            "raw_length": len(raw_response),
            "qa_pairs": [qa.model_dump() for qa in pairs],
            "count": len(pairs),
            "error": error,
        }
