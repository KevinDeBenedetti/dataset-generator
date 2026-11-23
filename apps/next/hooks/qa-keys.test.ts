import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'
import { invalidateDatasetQA, qaKey, qaStatsKey } from './qa-keys'

describe('invalidateDatasetQA', () => {
  it("marks every Q&A view of the dataset stale, and only that dataset's", async () => {
    const client = new QueryClient()
    client.setQueryData(qaStatsKey('docs', 0.7), { total: 10 })
    client.setQueryData(qaKey('docs', 10, 0), { qa_data: [] })
    client.setQueryData(qaStatsKey('other', 0.7), { total: 3 })

    await invalidateDatasetQA(client, 'docs')

    const state = (key: readonly unknown[]) => client.getQueryState(key)?.isInvalidated
    expect(state(qaStatsKey('docs', 0.7))).toBe(true)
    expect(state(qaKey('docs', 10, 0))).toBe(true)
    expect(state(qaStatsKey('other', 0.7))).toBe(false)
  })
})
