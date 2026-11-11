"""Measure the embedding checks' thresholds for one embedding model.

Each model scores on its own cosine scale: the defaults (core/config.py) were
measured on a small local model, and an endpoint model scores lower. A
built-in labeled set — short texts in English and French about a resume and
software projects — is embedded with the model, and each threshold is put
where it best separates its two kinds of examples:

* duplicates: a question and its rephrasing, against look-alike questions
  about something else;
* grounding: an answer faithful to its source, against a wrong or off-topic
  one;
* coverage: a section and a question about it, against a question about
  another section.

The same input every time, embedding calls only. A user's chosen model and
its thresholds are saved (``model_defaults`` role ``embedding``, the
``embedding_calibrations`` table) and used by every check of their datasets
(services/semantic.py ``embedding_choice``).
"""

import logging
import statistics
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from server.core.database import get_scoped_db
from server.models.embedding_calibration import EmbeddingCalibration
from server.models.model_defaults import ModelDefault
from server.services.semantic import (
    ENDPOINT_PREFIX,
    Embedder,
    Thresholds,
    grounding_scores,
    normalize,
    split_sections,
)

logger = logging.getLogger(__name__)

EMBEDDING_ROLE = "embedding"

# (question, its rephrasing)
REPHRASINGS: Tuple[Tuple[str, str], ...] = (
    ("What does Kevin do at Acme?", "What is Kevin's role at Acme?"),
    (
        "Which programming languages does Kevin use?",
        "What languages does Kevin program in?",
    ),
    (
        "Where did Kevin study computer science?",
        "Which school did Kevin attend for computer science?",
    ),
    ("How can I contact Kevin?", "What is the best way to reach Kevin?"),
    (
        "What is the portfolio project built with?",
        "Which technologies does the portfolio project use?",
    ),
    (
        "Does Kevin have experience with Kubernetes?",
        "Has Kevin worked with Kubernetes before?",
    ),
    ("What problem does dataset-generator solve?", "What is dataset-generator for?"),
    (
        "How long has Kevin worked as a developer?",
        "For how many years has Kevin been a developer?",
    ),
    (
        "Which cloud providers has Kevin used?",
        "What cloud platforms does Kevin have experience with?",
    ),
    ("How do I install the CLI?", "What are the installation steps for the CLI?"),
    (
        "Quel est le poste actuel de Kevin ?",
        "Quel poste Kevin occupe-t-il aujourd'hui ?",
    ),
    ("Quelles langues parle Kevin ?", "Kevin parle quelles langues ?"),
    ("Où Kevin a-t-il fait ses études ?", "Dans quelle école Kevin a-t-il étudié ?"),
    ("Comment contacter Kevin ?", "Comment puis-je joindre Kevin ?"),
    (
        "Quelles technologies Kevin utilise-t-il au quotidien ?",
        "Avec quels outils Kevin travaille-t-il chaque jour ?",
    ),
    (
        "Kevin est-il disponible pour une mission ?",
        "Kevin accepte-t-il de nouvelles missions ?",
    ),
)

# (question, a look-alike about something else): same shape, another answer.
LOOK_ALIKES: Tuple[Tuple[str, str], ...] = (
    ("What does Kevin do at Acme?", "What did Kevin do at Globex?"),
    ("Which programming languages does Kevin use?", "Which databases does Kevin use?"),
    ("Where did Kevin study computer science?", "Where does Kevin live?"),
    ("How can I contact Kevin?", "How can I deploy the portfolio?"),
    (
        "What is the portfolio project built with?",
        "What is the dataset-generator project built with?",
    ),
    (
        "Does Kevin have experience with Kubernetes?",
        "Does Kevin have experience with mobile apps?",
    ),
    (
        "What problem does dataset-generator solve?",
        "What license does dataset-generator use?",
    ),
    (
        "How long has Kevin worked as a developer?",
        "How long does a build of the image take?",
    ),
    ("Which cloud providers has Kevin used?", "Which certifications does Kevin hold?"),
    ("How do I install the CLI?", "How do I configure the CLI's output format?"),
    ("Quel est le poste actuel de Kevin ?", "Quel est le diplôme de Kevin ?"),
    ("Quelles langues parle Kevin ?", "Quels frameworks Kevin utilise-t-il ?"),
    ("Où Kevin a-t-il fait ses études ?", "Où Kevin travaille-t-il en ce moment ?"),
    ("Comment contacter Kevin ?", "Comment lancer le projet en local ?"),
    (
        "Quelles technologies Kevin utilise-t-il au quotidien ?",
        "Quels projets open source Kevin a-t-il publiés ?",
    ),
    (
        "Kevin est-il disponible pour une mission ?",
        "Kevin a-t-il déjà encadré une équipe ?",
    ),
)

# (source, a question about it, a faithful answer, a wrong one, an off-topic one)
SOURCES: Tuple[Tuple[str, str, str, str, str], ...] = (
    (
        "Lead developer at Acme since 2023. Built the ingestion platform in Go on "
        "Kafka, which processes four million events a day, and cut the "
        "infrastructure costs by 40%.",
        "What did Kevin build at Acme?",
        "At Acme, Kevin built a Go ingestion platform on Kafka handling four "
        "million events daily, and reduced the infrastructure costs by 40%.",
        "At Acme, Kevin led the mobile team and shipped the iOS app in Swift.",
        "The museum opens at nine and closes at six on Sundays.",
    ),
    (
        "MSc in Computer Science, INSA Lyon, 2014–2019. Thesis on distributed "
        "caching for stream processing.",
        "Where did Kevin study?",
        "Kevin holds an MSc in Computer Science from INSA Lyon, with a thesis on "
        "distributed caching for stream processing.",
        "Kevin studied law at the Sorbonne and graduated in 2010.",
        "Bake the bread for forty minutes at 220 degrees.",
    ),
    (
        "dataset-generator turns PDFs, web pages and GitHub repositories into "
        "question/answer datasets published privately on Hugging Face, with a "
        "review step before anything is published.",
        "What does dataset-generator do?",
        "dataset-generator builds question/answer datasets from PDFs, web pages "
        "and GitHub repositories, and publishes them privately on Hugging Face "
        "after a review.",
        "dataset-generator is a video editor that exports clips to YouTube.",
        "The train to Marseille leaves from platform four.",
    ),
    (
        "Skills: Python (FastAPI, SQLAlchemy), Go, TypeScript (Next.js), "
        "PostgreSQL, Kubernetes, Terraform.",
        "What are Kevin's main skills?",
        "Kevin's skills include Python with FastAPI and SQLAlchemy, Go, "
        "TypeScript with Next.js, PostgreSQL, Kubernetes and Terraform.",
        "Kevin mainly works with Java, Spring and Oracle databases.",
        "Tomatoes need six hours of sun a day.",
    ),
    (
        "Développeur backend chez Globex de 2019 à 2023 : services de facturation "
        "en Python, migration de la base vers PostgreSQL et mise en place de "
        "l'intégration continue.",
        "Qu'a fait Kevin chez Globex ?",
        "Chez Globex, Kevin a développé des services de facturation en Python, "
        "migré la base vers PostgreSQL et mis en place l'intégration continue.",
        "Chez Globex, Kevin était responsable marketing et gérait les réseaux sociaux.",
        "Le marché ouvre le samedi matin sur la place de la mairie.",
    ),
    (
        "Langues : français (langue maternelle), anglais (C1, usage professionnel "
        "quotidien), espagnol (notions).",
        "Quelles langues parle Kevin ?",
        "Kevin parle français, sa langue maternelle, anglais au niveau C1 et a "
        "des notions d'espagnol.",
        "Kevin parle couramment allemand et japonais.",
        "Il faut arroser les géraniums deux fois par semaine.",
    ),
    (
        "To deploy, build the image with make build, push it to the registry, then "
        "run helm upgrade with the values file of the environment. Migrations run "
        "as a Kubernetes Job before the pods roll.",
        "How is the project deployed?",
        "Deployment builds the image with make build, pushes it to the registry "
        "and runs helm upgrade with the environment's values file; migrations run "
        "in a Kubernetes Job first.",
        "Deployment is done by copying the files over FTP to a shared host.",
        "The festival lineup will be announced in March.",
    ),
    (
        "The portfolio is a Next.js site with a chat assistant that answers "
        "questions about Kevin from his resume and his public GitHub "
        "repositories, retrieved from a Qdrant collection.",
        "What is Kevin's portfolio?",
        "Kevin's portfolio is a Next.js site whose chat assistant answers from his "
        "resume and GitHub repositories, retrieved from Qdrant.",
        "The portfolio is a WordPress blog without any search feature.",
        "Penguins mostly live in the southern hemisphere.",
    ),
)

# A threshold stays within these, whatever a strange model scores.
_LOWEST, _HIGHEST = 0.05, 0.99


def best_threshold(
    positives: Sequence[float], negatives: Sequence[float]
) -> Tuple[float, float]:
    """``(threshold, balanced accuracy)``: the line that best separates the
    positives (at or above it) from the negatives (below it). Between two
    equally good lines, the middle one, so both sides keep a margin."""
    scores = sorted(set(positives) | set(negatives))
    candidates = [(a + b) / 2 for a, b in zip(scores, scores[1:], strict=False)]
    candidates = candidates or scores

    def balanced(line: float) -> float:
        caught = sum(p >= line for p in positives) / len(positives)
        spared = sum(n < line for n in negatives) / len(negatives)
        return (caught + spared) / 2

    best = max(balanced(c) for c in candidates)
    winners = [c for c in candidates if balanced(c) == best]
    line = winners[len(winners) // 2]
    return round(min(_HIGHEST, max(_LOWEST, line)), 3), round(best, 3)


def _spread(values: Sequence[float]) -> Dict[str, float]:
    return {
        "min": round(min(values), 3),
        "median": round(statistics.median(values), 3),
        "max": round(max(values), 3),
    }


def _check(positives: List[float], negatives: List[float]) -> Dict[str, Any]:
    threshold, accuracy = best_threshold(positives, negatives)
    return {
        "threshold": threshold,
        "accuracy": accuracy,
        "positives": _spread(positives),
        "negatives": _spread(negatives),
        "examples": len(positives) + len(negatives),
    }


def measure(embedder: Embedder) -> Dict[str, Any]:
    """Embed the labeled set with ``embedder`` and measure each threshold.
    Blocking (the embedding calls); raises the embedder's errors."""
    texts: List[str] = []
    for pair in REPHRASINGS + LOOK_ALIKES:
        texts += pair
    for source, question, *answers in SOURCES:
        texts += [source, question, *answers]
    unique = list(dict.fromkeys(texts))
    vectors = dict(zip(unique, normalize(embedder.embed(unique)), strict=True))

    def cosine(a: str, b: str) -> float:
        return float(vectors[a] @ vectors[b])

    dedup = _check(
        [cosine(a, b) for a, b in REPHRASINGS], [cosine(a, b) for a, b in LOOK_ALIKES]
    )

    faithful: List[float] = []
    unfaithful: List[float] = []
    covered: List[float] = []
    uncovered: List[float] = []
    for i, (source, question, right, wrong, off) in enumerate(SOURCES):
        chunks = np.array([vectors[source]])
        for chunk in split_sections(source)[1:]:  # a long source: every chunk
            chunks = np.vstack([chunks, normalize(embedder.embed([chunk]))])
        faithful.append(float(grounding_scores(vectors[right], chunks)[0]))
        unfaithful += [
            float(grounding_scores(vectors[wrong], chunks)[0]),
            float(grounding_scores(vectors[off], chunks)[0]),
        ]
        covered.append(cosine(source, question))
        other = SOURCES[(i + 3) % len(SOURCES)][1]
        uncovered.append(cosine(source, other))

    return {
        "model": embedder.model_name,
        "dedup": dedup,
        "grounding": _check(faithful, unfaithful),
        "uncovered": _check(covered, uncovered),
    }


def thresholds_from(report: Dict[str, Any]) -> Thresholds:
    return Thresholds(
        dedup=report["dedup"]["threshold"],
        grounding=report["grounding"]["threshold"],
        uncovered=report["uncovered"]["threshold"],
    )


# --- the user's choice ----------------------------------------------------------------


def load_choice(
    user_id: str, default_model_id: str
) -> Tuple[str, Optional[Thresholds]]:
    """``(chosen model id or '', thresholds measured for the model in effect)``
    — the chosen one, else ``default_model_id``. Blocking (the database)."""
    with get_scoped_db() as db:
        row = db.get(ModelDefault, {"user_id": user_id, "role": EMBEDDING_ROLE})
        chosen = (row.model_ref if row else "") or ""
        chosen_id = chosen.removeprefix(ENDPOINT_PREFIX)
        model_id = chosen_id or default_model_id
        if not model_id:
            return chosen_id, None
        calibration = db.get(
            EmbeddingCalibration,
            {"user_id": user_id, "model_ref": ENDPOINT_PREFIX + model_id},
        )
        if calibration is None:
            return chosen_id, None
        return chosen_id, Thresholds(
            calibration.dedup, calibration.grounding, calibration.uncovered
        )


def calibration_report(user_id: str, model_ref: str) -> Optional[Dict[str, Any]]:
    """The saved measurement of ``model_ref`` for the user, with its date."""
    if not model_ref:
        return None
    with get_scoped_db() as db:
        row = db.get(EmbeddingCalibration, {"user_id": user_id, "model_ref": model_ref})
        if row is None:
            return None
        return {**(row.report or {}), "measured_at": row.measured_at}


def save_choice(user_id: str, model_ref: str, report: Dict[str, Any]) -> None:
    """Use ``model_ref`` for the user's checks, with the measured thresholds."""
    now = datetime.now(timezone.utc)
    thresholds = thresholds_from(report)
    with get_scoped_db() as db:
        row = db.get(ModelDefault, {"user_id": user_id, "role": EMBEDDING_ROLE})
        if row is None:
            db.add(
                ModelDefault(user_id=user_id, role=EMBEDDING_ROLE, model_ref=model_ref)
            )
        else:
            row.model_ref = model_ref
            row.updated_at = now
        calibration = db.get(
            EmbeddingCalibration, {"user_id": user_id, "model_ref": model_ref}
        )
        if calibration is None:
            calibration = EmbeddingCalibration(user_id=user_id, model_ref=model_ref)
            db.add(calibration)
        calibration.dedup = thresholds.dedup
        calibration.grounding = thresholds.grounding
        calibration.uncovered = thresholds.uncovered
        calibration.report = report
        calibration.measured_at = now
        db.commit()
    logger.info("embedding model %s measured and chosen: %s", model_ref, thresholds)


def reset_choice(user_id: str) -> None:
    """Back to the server's model (its thresholds stay, if measured)."""
    with get_scoped_db() as db:
        row = db.get(ModelDefault, {"user_id": user_id, "role": EMBEDDING_ROLE})
        if row is not None:
            db.delete(row)
            db.commit()
