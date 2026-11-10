import { describe, expect, it } from 'vitest'
import {
  defaultCollectionName,
  defaultColumns,
  isTrivialTest,
  modelLabel,
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
