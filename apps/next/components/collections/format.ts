// Pure helpers of the Collections pages: labels, defaults, links, the snippet.

import { datasetHref } from '../hub/format'

/** A collection model is one of the OpenAI-compatible endpoint's, named
 * `openai:<id>` (services/semantic.py); a collection built before the local
 * models were removed still names one of those. */
export const ENDPOINT_PREFIX = 'openai:'

export function isEndpointModel(name: string): boolean {
  return name.startsWith(ENDPOINT_PREFIX)
}

/** A collection built with a local model, which the server no longer runs:
 * its vectors are still in Qdrant, but nothing can embed a question for them,
 * and a rebuild keeps the same model. It has to be made again. */
export function modelRemoved(collection: { model: string }): boolean {
  return !isEndpointModel(collection.model)
}

/** `BAAI/bge-small-en-v1.5` → `bge-small-en-v1.5`; `openai:embed-default` → `embed-default`. */
export function modelLabel(name: string): string {
  const id = isEndpointModel(name) ? name.slice(ENDPOINT_PREFIX.length) : name
  return id.slice(id.lastIndexOf('/') + 1)
}

/** 0.754 → `75%`; 1 → `100%`; a share under 1% but above 0 → `<1%`. */
export function percent(share: number | null | undefined): string {
  if (share == null || Number.isNaN(share)) return '—'
  if (share > 0 && share < 0.01) return '<1%'
  return `${Math.round(share * 100)}%`
}

/** A suggested name: the dataset, its split when not "train", the model. */
export function defaultCollectionName(repoId: string, split: string, model: string): string {
  const dataset = repoId.slice(repoId.indexOf('/') + 1)
  const parts = [dataset, split && split !== 'train' ? split : null, modelLabel(model)]
  return parts.filter(Boolean).join(' · ').slice(0, 100)
}

export interface SplitColumns {
  /** Text columns of the split, in its order. */
  strings: string[]
  /** The question/answer/context columns the viewer detected, if any. */
  qa?: { question: string; answer: string; context?: string | null } | null
}

/** What a new collection embeds and asks with, by default: for a Q/A split,
 * the answer (and its context) embedded and the question to test with — the
 * test then tells whether each question finds its answer. Otherwise the first
 * text column, and no test column. */
export function defaultColumns({ strings, qa }: SplitColumns): {
  text: string[]
  query: string | null
} {
  if (qa) {
    return {
      text: [qa.answer, ...(qa.context ? [qa.context] : [])],
      query: qa.question,
    }
  }
  return { text: strings.slice(0, 1), query: null }
}

/** The query column is embedded too: every row finds its own text. */
export function isTrivialTest(textColumns: string[], queryColumn: string | null): boolean {
  return queryColumn != null && textColumns.includes(queryColumn)
}

/** What the comparison needs of a collection (a `CollectionOut` has it all). */
export interface ComparedCollection {
  id: string
  name: string
  repo_id: string
  revision: string
  config: string
  split: string
  model: string
  text_columns: string[]
  status: string
  evaluation?: {
    query_column: string
    sample: number
    k: number
    queries: number
    hit_at_1: number
    hit_at_k: number
    mrr: number
    trivial?: boolean
  } | null
}

export interface ComparisonRow {
  collection: ComparedCollection
  current: boolean
  /** Why its figures can't be read next to the current collection's, if so. */
  caveat: string | null
}

/** The collections to read side by side with `current`: those of the same
 * split at the same commit — the retrieval test samples the same rows for all
 * of them — best first. A test run with another question column, sample size
 * or top k is listed with a caveat, an untested collection last. Empty when
 * `current` is the only collection of its split. */
export function comparisonRows(
  current: ComparedCollection,
  all: ComparedCollection[],
): ComparisonRow[] {
  const same = (c: ComparedCollection) =>
    c.repo_id === current.repo_id &&
    c.revision === current.revision &&
    c.config === current.config &&
    c.split === current.split
  const others = all.filter((c) => c.id !== current.id && same(c))
  if (others.length === 0) return []
  const reference = current.evaluation
  const caveat = (c: ComparedCollection): string | null => {
    const test = c.evaluation
    if (!test) return c.status === 'ready' ? 'Not tested yet' : 'Not built'
    if (test.trivial) return `${test.query_column} is embedded too: every row finds itself`
    if (!reference || c.id === current.id) return null
    if (test.query_column !== reference.query_column) return `Asked with ${test.query_column}`
    if (test.sample !== reference.sample) return `Tested on ${test.sample} sampled rows`
    if (test.k !== reference.k) return `Top ${test.k}`
    return null
  }
  const score = (c: ComparedCollection) =>
    c.evaluation ? [c.evaluation.hit_at_1, c.evaluation.mrr] : [-1, -1]
  return [current, ...others]
    .map((collection) => ({
      collection,
      current: collection.id === current.id,
      caveat: caveat(collection),
    }))
    .toSorted((a, b) => {
      const [a1, a2] = score(a.collection)
      const [b1, b2] = score(b.collection)
      return b1 - a1 || b2 - a2 || a.collection.name.localeCompare(b.collection.name)
    })
}

/** A top hit this close to the expected row's own text is most likely the
 * same pair twice. */
export const DUPLICATE_SCORE = 0.95

/** The dataset viewer on one row of the split, at the collection's commit. */
export function rowHref(
  collection: { repo_id: string; revision: string; config: string; split: string },
  rowIdx: number,
): string {
  const params = new URLSearchParams({ rev: collection.revision })
  if (collection.config !== 'default') params.set('config', collection.config)
  params.set('split', collection.split)
  params.set('row', String(rowIdx))
  return `${datasetHref(collection.repo_id)}?${params.toString()}`
}

/** Python that queries the collection outside the app: same model, same name. */
export function pythonSnippet(collection: { model: string; qdrant_collection: string }): string {
  return [
    'from openai import OpenAI',
    'from qdrant_client import QdrantClient',
    '',
    '# The OpenAI-compatible endpoint and key the collection was built with.',
    'llm = OpenAI(base_url="https://your-endpoint/v1", api_key="sk-…")',
    '# QDRANT_URL of the server; the local stack publishes it on localhost:6353.',
    'client = QdrantClient(url="http://localhost:6353")',
    '',
    'vector = llm.embeddings.create(',
    `    model=${JSON.stringify(modelId(collection.model))}, input="your question"`,
    ').data[0].embedding',
    'hits = client.query_points(',
    `    ${JSON.stringify(collection.qdrant_collection)}, query=vector, limit=5`,
    ').points',
    'for hit in hits:',
    '    print(round(hit.score, 3), hit.payload["text"][:80])',
  ].join('\n')
}

/** The id the endpoint knows a model by: `openai:embed-default` → `embed-default`. */
function modelId(name: string): string {
  return isEndpointModel(name) ? name.slice(ENDPOINT_PREFIX.length) : name
}
