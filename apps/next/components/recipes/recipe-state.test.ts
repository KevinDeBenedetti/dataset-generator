import { describe, expect, it } from 'vitest'
import type { RecipePreview } from '../../api/sdk'
import {
  columnsBefore,
  corpusOptions,
  filterValue,
  moveStep,
  newStep,
  removeStep,
  repoSlug,
  replaceStep,
  reviewHref,
  STEP_OPS,
} from './recipe-state'

const COLUMNS = [
  { name: 'code', type: 'VARCHAR' },
  { name: 'pop', type: 'BIGINT' },
]

describe('newStep', () => {
  it('makes every op valid on the current columns', () => {
    for (const op of STEP_OPS) expect(newStep(op, COLUMNS).op).toBe(op)
    expect(newStep('select', COLUMNS)).toEqual({ op: 'select', columns: ['code', 'pop'] })
    expect(newStep('mask', COLUMNS)).toEqual({ op: 'mask', column: 'code', method: 'hash' })
  })
})

describe('step list', () => {
  const steps = [newStep('trim', COLUMNS), newStep('limit', COLUMNS)]
  it('moves, removes and replaces', () => {
    expect(moveStep(steps, 0, 1).map((s) => s.op)).toEqual(['limit', 'trim'])
    expect(moveStep(steps, 0, -1)).toBe(steps)
    expect(removeStep(steps, 0).map((s) => s.op)).toEqual(['limit'])
    expect(replaceStep(steps, 1, { op: 'limit', rows: 5 })[1]).toEqual({ op: 'limit', rows: 5 })
  })
})

describe('columnsBefore', () => {
  const preview = {
    source_schema: COLUMNS,
    step_schemas: [[COLUMNS[0]]],
    schema: [COLUMNS[0]],
  } as unknown as RecipePreview
  it('reads the source for the first step, the previous output after', () => {
    expect(columnsBefore(preview, 0)).toEqual(COLUMNS)
    expect(columnsBefore(preview, 1)).toEqual([COLUMNS[0]])
    expect(columnsBefore(undefined, 0)).toEqual([])
  })
})

describe('filterValue', () => {
  it('reads what the operator expects', () => {
    expect(filterValue('in', 'a, b,')).toEqual(['a', 'b'])
    expect(filterValue('ge', '2000')).toBe(2000)
    expect(filterValue('eq', 'Argol')).toBe('Argol')
    expect(filterValue('contains', '12')).toBe('12')
    expect(filterValue('is_null', 'x')).toBeUndefined()
  })
})

describe('repoSlug', () => {
  it('makes a Hub repo name', () => {
    expect(repoSlug('Communes du Finistère')).toBe('communes-du-finistere')
    expect(repoSlug('***')).toBe('dataset')
  })
})

describe('drafts by kind', () => {
  it('sends Q&A drafts to the drafts page', () => {
    expect(reviewHref('r1', 'qa')).toBe('/drafts/runs/r1')
    expect(reviewHref('r1', 'qa_llm')).toBe('/drafts/runs/r1')
    expect(reviewHref('r1', 'corpus')).toBe('/runs/r1/review')
    expect(reviewHref('r1', null)).toBe('/runs/r1/review')
  })

  it('drops the corpus fields left blank', () => {
    const blank = {
      text_template: '{nom}',
      title_template: '',
      id_column: '',
      chunk_chars: '',
      metadata_columns: [],
    }
    expect(corpusOptions(blank)).toEqual({ text_template: '{nom}' })
    expect(corpusOptions({ ...blank, chunk_chars: '800', metadata_columns: ['dep'] })).toEqual({
      text_template: '{nom}',
      chunk_chars: 800,
      metadata_columns: ['dep'],
    })
  })
})
