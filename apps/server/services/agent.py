"""QA generation agent.

Runs as a single-node LangGraph graph wrapping a LangChain ``ChatOpenAI`` model
pointed at the configured OpenAI-compatible endpoint. The model is instructed
to emit a JSON list of QA pairs, which we parse tolerantly ourselves (see
``_parse_qa_list``) rather than relying on LangChain structured output —
reasoning-heavy / gpt-oss-style models can still truncate or wrap the JSON,
and the diagnostic endpoint needs the raw text regardless of whether it parses.
The graph is a placeholder for now (one node, no branching) but gives the
agent room to grow into multi-step behaviour (retries, validation) later.
"""

import functools
import json
import logging
import re
from collections import Counter
from typing import Any, List, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
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


def _salvage_objects(text: str) -> list:
    """Recover every complete JSON object from a possibly-truncated response.

    Reasoning models or a hit token budget (``max_tokens_qa``) can cut the
    response off mid-array, leaving the outer JSON unparseable. This scans for
    balanced ``{...}`` spans at any nesting depth, honouring string literals and
    escapes so a brace inside an ``answer``/``context`` value (or a nested JSON
    object) doesn't terminate the span early. Each closed object is parsed; the
    complete ones survive even when the surrounding structure is truncated.
    """
    objects: list = []
    stack: List[int] = []
    in_string = False
    escaped = False
    for i, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            stack.append(i)
        elif ch == "}" and stack:
            start = stack.pop()
            try:
                objects.append(json.loads(text[start : i + 1]))
            except Exception:
                continue
    return objects


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

    # Build candidate item-lists from every JSON form we can find: the outermost
    # array, the outermost object, then a brace-salvage of complete objects. We
    # try them in order and return the first that yields a valid pair — so a
    # valid object elsewhere isn't lost when an earlier array exists but every
    # one of its items fails validation.
    candidates: List[list] = []
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
            candidates.append(data)
        elif isinstance(data, dict):
            candidates.append(
                data["items"] if isinstance(data.get("items"), list) else [data]
            )

    salvaged = _salvage_objects(cleaned)
    if salvaged:
        candidates.append(salvaged)

    last_raw: list = []
    for raw_items in candidates:
        if not raw_items:
            continue
        last_raw = raw_items
        items = _coerce_items(raw_items)
        if items:
            return items

    if not last_raw:
        logging.warning(
            "QA model response could not be parsed as QA pairs — no JSON found. "
            "Raw response: %s",
            _truncate_for_log(cleaned),
        )
        return []

    logging.warning(
        "QA model returned %d candidate item(s) but none passed validation "
        "(see skip summary). Raw response: %s",
        len(last_raw),
        _truncate_for_log(cleaned),
    )
    return []


class _AgentState(TypedDict):
    text: str
    target_language: str
    model: str
    raw_response: str


class QAAgentService:
    """Generate QA pairs via a single-node LangGraph graph over ChatOpenAI."""

    def _build_chat_model(self, model: str) -> Any:
        # Imported lazily: langchain_openai builds a module-level SSL context
        # (via certifi) at import time, which some sandboxes block — same
        # reason LLMService/QAAgentService keep their openai clients lazy.
        from langchain_openai import ChatOpenAI

        # Built per call (not cached) since the model id varies per request;
        # construction itself is cheap and does no I/O.
        kwargs: dict = dict(
            model=model,
            api_key=config.openai_api_key,
            base_url=config.openai_base_url or None,
            max_tokens=config.max_tokens_qa,
            temperature=config.temperature,
        )
        # "low" keeps gpt-oss-style models from spending their whole budget
        # reasoning and never emitting the final JSON.
        if config.openai_reasoning_effort:
            kwargs["reasoning_effort"] = config.openai_reasoning_effort
        return ChatOpenAI(**kwargs)

    async def _generate_node(self, state: _AgentState) -> dict:
        chat_model = self._build_chat_model(state["model"])
        prompt = (
            f"Target language: {state['target_language']}\n\n"
            f"Source text:\n{state['text']}"
        )
        response = await chat_model.ainvoke(
            [
                {"role": "system", "content": QA_AGENT_INSTRUCTION},
                {"role": "user", "content": prompt},
            ]
        )
        content = response.content if isinstance(response.content, str) else ""
        return {"raw_response": content.strip()}

    @functools.cached_property
    def _graph(self):
        # ty (unlike pyright/mypy) doesn't accept a TypedDict class against
        # StateGraph's StateT bound here; this is the documented langgraph
        # usage (see langgraph.graph.StateGraph docs).
        graph = StateGraph(_AgentState)  # ty: ignore[invalid-argument-type]
        graph.add_node("generate", self._generate_node)
        graph.add_edge(START, "generate")
        graph.add_edge("generate", END)
        return graph.compile()

    async def _run(self, text: str, target_language: str, model: str) -> str:
        """Run the graph once and return the model's raw response text."""
        result = await self._graph.ainvoke(
            {"text": text, "target_language": target_language, "model": model}
        )
        return result["raw_response"]

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
