// The recipe editor's pure logic: new steps, moves, which columns a step sees
// (kept apart from the components so vitest checks it without a DOM).
import type { RecipePreview, RecipeStep, SchemaColumn } from '@/api/sdk'

export const STEP_OPS = [
  'select',
  'rename',
  'cast',
  'filter',
  'dedup',
  'mask',
  'trim',
  'limit',
] as const
export type StepOp = (typeof STEP_OPS)[number]

export const CAST_TARGETS = ['integer', 'double', 'date', 'timestamp', 'boolean', 'text'] as const
export const FILTER_OPERATORS = [
  'eq',
  'ne',
  'lt',
  'le',
  'gt',
  'ge',
  'in',
  'not_in',
  'contains',
  'is_null',
  'not_null',
] as const
export const MASK_METHODS = ['hash', 'redact', 'truncate', 'drop'] as const

// A step of kind `op`, filled with what the table has at that point.
export function newStep(op: StepOp, columns: SchemaColumn[]): RecipeStep {
  const first = columns[0]?.name ?? ''
  switch (op) {
    case 'select':
      return { op, columns: columns.map((c) => c.name) }
    case 'rename':
      return { op, mapping: first ? { [first]: first } : {} }
    case 'cast':
      return { op, column: first, to: 'text', on_error: 'null' }
    case 'filter':
      return { op, column: first, operator: 'not_null' }
    case 'dedup':
      return { op, columns: [], keep: 'first' }
    case 'mask':
      return { op, column: first, method: 'hash' }
    case 'trim':
      return { op, columns: [] }
    case 'limit':
      return { op, rows: 1000 }
  }
}

export function moveStep(steps: RecipeStep[], index: number, by: -1 | 1): RecipeStep[] {
  const target = index + by
  if (target < 0 || target >= steps.length) return steps
  const next = [...steps]
  ;[next[index], next[target]] = [next[target], next[index]]
  return next
}

export function removeStep(steps: RecipeStep[], index: number): RecipeStep[] {
  return steps.filter((_, i) => i !== index)
}

export function replaceStep(steps: RecipeStep[], index: number, step: RecipeStep): RecipeStep[] {
  return steps.map((s, i) => (i === index ? step : s))
}

// The columns step `index` reads: the data source's for the first step, the
// previous step's output afterwards (from the last preview).
export function columnsBefore(preview: RecipePreview | undefined, index: number): SchemaColumn[] {
  if (!preview) return []
  if (index === 0) return preview.source_schema ?? []
  return preview.step_schemas?.[index - 1] ?? preview.schema ?? []
}

// A filter value as the user typed it: a list for `in`/`not_in`, a number when
// it reads as one, the text otherwise; none for the null checks.
export function filterValue(operator: string, text: string): unknown {
  if (operator === 'is_null' || operator === 'not_null') return undefined
  if (operator === 'in' || operator === 'not_in') {
    return text
      .split(',')
      .map((v) => v.trim())
      .filter(Boolean)
  }
  if (operator === 'contains') return text
  const n = Number(text)
  return text.trim() !== '' && Number.isFinite(n) ? n : text
}

// A Hub repo name from a data source's name ("Communes du Finistère" →
// "communes-du-finistere").
export function repoSlug(name: string): string {
  return (
    name
      .normalize('NFD')
      .replace(/[̀-ͯ]/g, '')
      .toLowerCase()
      .replace(/[^a-z0-9._-]+/g, '-')
      .replace(/^[-.]+|[-.]+$/g, '')
      .slice(0, 96) || 'dataset'
  )
}

// Where a run's draft is reviewed: Q&A drafts on the drafts page, tables and
// corpora on the run's review page.
export function reviewHref(runId: string, kind: string | null | undefined): string {
  return kind === 'qa' || kind === 'qa_llm' ? `/drafts/runs/${runId}` : `/runs/${runId}/review`
}

export interface CorpusForm {
  text_template: string
  title_template: string
  id_column: string
  chunk_chars: string
  metadata_columns: string[]
}

// The corpus output's options, without the fields left blank.
export function corpusOptions(form: CorpusForm): Record<string, unknown> {
  const out: Record<string, unknown> = { text_template: form.text_template }
  if (form.title_template) out.title_template = form.title_template
  if (form.id_column) out.id_column = form.id_column
  if (form.chunk_chars) out.chunk_chars = Number(form.chunk_chars)
  if (form.metadata_columns.length) out.metadata_columns = form.metadata_columns
  return out
}
