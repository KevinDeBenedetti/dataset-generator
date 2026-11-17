import { describe, expect, it } from 'vitest'
import {
  type ComparedCollection,
  comparisonRows,
  defaultCollectionName,
  defaultColumns,
  endpointMoved,
  isTrivialTest,
  modelLabel,
  modelRemoved,
  percent,
  pythonSnippet,
  rowHref,
} from './format'

describe('collection labels', () => {
  it('names a model by its last segment', () => {
    expect(modelLabel('BAAI/bge-small-en-v1.5')).toBe('bge-small-en-v1.5')
    expect(modelLabel('plain')).toBe('plain')
    expect(modelLabel('openai:embed-default')).toBe('embed-default')
  })

  it('tells a collection built on another endpoint than yours now', () => {
    expect(endpointMoved({ status: 'ready', current_endpoint: 'llm.example.com' })).toBe(true)
    expect(endpointMoved({ status: 'failed', current_endpoint: 'llm.example.com' })).toBe(true)
    expect(endpointMoved({ status: 'building', current_endpoint: 'llm.example.com' })).toBe(false)
    expect(endpointMoved({ status: 'ready', current_endpoint: null })).toBe(false)
  })

  it('tells a collection whose local model is gone', () => {
    expect(modelRemoved({ model: 'BAAI/bge-small-en-v1.5' })).toBe(true)
    expect(modelRemoved({ model: 'openai:embed-default' })).toBe(false)
  })

  it('rounds shares to whole percents, flagging the tiny ones', () => {
    expect(percent(0.754)).toBe('75%')
    expect(percent(1)).toBe('100%')
    expect(percent(0)).toBe('0%')
    expect(percent(0.004)).toBe('<1%')
    expect(percent(null)).toBe('—')
  })

  it('suggests a name from the dataset, a non-train split and the model', () => {
    expect(defaultCollectionName('kevin/github-qa', 'train', 'BAAI/bge-small-en-v1.5')).toBe(
      'github-qa · bge-small-en-v1.5',
    )
    expect(defaultCollectionName('kevin/qa', 'test', 'm/mini')).toBe('qa · test · mini')
  })
})

describe('default columns', () => {
  it('embeds the answer and its context, and tests with the question', () => {
    const qa = { question: 'question', answer: 'answer', context: 'context' }
    expect(defaultColumns({ strings: ['id', 'question', 'answer', 'context'], qa })).toEqual({
      text: ['answer', 'context'],
      query: 'question',
    })
    expect(
      defaultColumns({ strings: ['q', 'a'], qa: { question: 'q', answer: 'a', context: null } }),
    ).toEqual({ text: ['a'], query: 'q' })
  })

  it('takes the first text column of any other split, with no test column', () => {
    expect(defaultColumns({ strings: ['title', 'body'], qa: null })).toEqual({
      text: ['title'],
      query: null,
    })
    expect(defaultColumns({ strings: [] })).toEqual({ text: [], query: null })
  })

  it('calls a test trivial when the question is embedded too', () => {
    expect(isTrivialTest(['question', 'answer'], 'question')).toBe(true)
    expect(isTrivialTest(['answer'], 'question')).toBe(false)
    expect(isTrivialTest(['answer'], null)).toBe(false)
  })
})

describe('links and snippet', () => {
  const collection = {
    repo_id: 'kevin/qa',
    revision: 'abc123',
    config: 'default',
    split: 'train',
    model: 'openai:embed-default',
    qdrant_collection: 'dataset_c_42',
  }

  it('opens the row in the dataset viewer at the collection commit', () => {
    expect(rowHref(collection, 7)).toBe('/datasets/kevin/qa?rev=abc123&split=train&row=7')
    expect(rowHref({ ...collection, config: 'en' }, 0)).toBe(
      '/datasets/kevin/qa?rev=abc123&config=en&split=train&row=0',
    )
  })

  it('queries the same collection with the same model, through the endpoint', () => {
    const snippet = pythonSnippet(collection)
    expect(snippet).toContain('llm.embeddings.create(')
    expect(snippet).toContain('model="embed-default"')
    expect(snippet).toContain('"dataset_c_42", query=vector')
  })
})

const test = (hit: number, extra = {}) => ({
  query_column: 'question',
  sample: 100,
  k: 10,
  queries: 100,
  hit_at_1: hit,
  hit_at_k: 0.95,
  mrr: hit,
  ...extra,
})
const collection = (id: string, extra: Partial<ComparedCollection> = {}): ComparedCollection => ({
  id,
  name: id,
  repo_id: 'kevin/github-qa',
  revision: 'abc',
  config: 'default',
  split: 'train',
  model: 'openai:embed-default',
  text_columns: ['answer'],
  status: 'ready',
  evaluation: test(0.5),
  ...extra,
})

describe('comparing the collections of one split', () => {
  it('has nothing to compare when the split has one collection', () => {
    const only = collection('a')
    expect(comparisonRows(only, [only])).toEqual([])
    expect(comparisonRows(only, [only, collection('b', { split: 'test' })])).toEqual([])
    expect(comparisonRows(only, [only, collection('b', { revision: 'def' })])).toEqual([])
    expect(comparisonRows(only, [only, collection('b', { repo_id: 'kevin/other' })])).toEqual([])
  })

  it('lists the collections of the same split and commit, best first', () => {
    const current = collection('a')
    const rows = comparisonRows(current, [
      collection('c', { evaluation: test(0.2) }),
      current,
      collection('b', { evaluation: test(0.9) }),
    ])
    expect(rows.map((r) => [r.collection.id, r.current, r.caveat])).toEqual([
      ['b', false, null],
      ['a', true, null],
      ['c', false, null],
    ])
  })

  it('says why a test cannot be read next to this one', () => {
    const current = collection('a')
    const caveats = Object.fromEntries(
      comparisonRows(current, [
        current,
        collection('column', { evaluation: test(0.5, { query_column: 'title' }) }),
        collection('sample', { evaluation: test(0.5, { sample: 500 }) }),
        collection('k', { evaluation: test(0.5, { k: 5 }) }),
        collection('trivial', { evaluation: test(1, { trivial: true }) }),
        collection('untested', { evaluation: null }),
        collection('building', { evaluation: null, status: 'building' }),
      ]).map((r) => [r.collection.id, r.caveat]),
    )
    expect(caveats).toEqual({
      a: null,
      column: 'Asked with title',
      sample: 'Tested on 500 sampled rows',
      k: 'Top 5',
      trivial: 'question is embedded too: every row finds itself',
      untested: 'Not tested yet',
      building: 'Not built',
    })
  })

  it('puts the collections without a test last', () => {
    const current = collection('a', { evaluation: null })
    const rows = comparisonRows(current, [current, collection('b', { evaluation: test(0.1) })])
    expect(rows.map((r) => r.collection.id)).toEqual(['b', 'a'])
    // Nothing to compare against: the tested one stands on its own.
    expect(rows[0].caveat).toBeNull()
  })
})
