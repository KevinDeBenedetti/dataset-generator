// Pure helpers of the Collections pages: labels, defaults, links, the snippet.

import { datasetHref } from '../hub/format'

/** A model of the OpenAI-compatible endpoint is named `openai:<id>`; any other
 * name is a local model (services/semantic.py). */
export const ENDPOINT_PREFIX = 'openai:'

export function isEndpointModel(name: string): boolean {
  return name.startsWith(ENDPOINT_PREFIX)
}

/** `BAAI/bge-small-en-v1.5` → `bge-small-en-v1.5`; `openai:embed-default` → `embed-default`. */
export function modelLabel(name: string): string {
  const id = isEndpointModel(name) ? name.slice(ENDPOINT_PREFIX.length) : name
  return id.slice(id.lastIndexOf('/') + 1)
}

/** The create form's model choices: the endpoint's first (the default), then
 * the local ones — empty groups left out, the server's order kept. */
export function modelGroups<T extends { name: string }>(
  models: T[],
): { label: string; models: T[] }[] {
  const groups = [
    { label: 'Your endpoint', models: models.filter((m) => isEndpointModel(m.name)) },
    { label: 'Local, on the server', models: models.filter((m) => !isEndpointModel(m.name)) },
  ]
  return groups.filter((g) => g.models.length > 0)
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
  const embedding = isEndpointModel(collection.model)
    ? [
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
      ]
    : [
        'from fastembed import TextEmbedding',
        'from qdrant_client import QdrantClient',
        '',
        `model = TextEmbedding(${JSON.stringify(collection.model)})`,
        '# QDRANT_URL of the server; the local stack publishes it on localhost:6353.',
        'client = QdrantClient(url="http://localhost:6353")',
        '',
        'vector = next(model.query_embed("your question")).tolist()',
      ]
  return [
    ...embedding,
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
