import { keepPreviousData, useQuery } from '@tanstack/react-query'
import {
  errorStatus,
  getHubCommits,
  getHubCompare,
  getHubDataset,
  getHubDatasets,
  getHubRow,
  getHubRows,
  getHubStatistics,
  type HubCompareQuery,
  type HubRepoRef,
  type HubRowsQuery,
  type HubSplitQuery,
} from '@/api/sdk'

// Every Hub view lives under this key, so a publish can invalidate them all.
export const HUB_QUERY_KEY = 'hub'

// Answers that won't change by asking again: bad request, not connected, not
// found, too large, unreadable. Only network blips and 5xx are retried.
const DEFINITIVE = new Set([400, 401, 403, 404, 413, 422, 503])

// Typed on Error (not unknown): React Query infers each query's error type
// from this signature.
function retryTransient(failureCount: number, error: Error): boolean {
  const status = errorStatus(error)
  return !(status != null && DEFINITIVE.has(status)) && failureCount < 2
}

// A full commit sha never changes content: what was read at it stays true.
const SHA = /^[0-9a-f]{40}$/
function staleTimeFor(revision?: string | null): number {
  return revision && SHA.test(revision) ? Infinity : 30_000
}

/** The dataset repos of one of your namespaces (default: your own). Switching
 * namespace keeps the previous list on screen until the next one arrives. */
export function useHubDatasets(author?: string | null) {
  return useQuery({
    queryKey: [HUB_QUERY_KEY, 'datasets', author ?? null],
    queryFn: () => getHubDatasets(author),
    retry: retryTransient,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  })
}

/** Metadata, card, files and tables of one dataset at a revision. */
export function useHubDataset(repo: HubRepoRef, revision?: string | null, enabled = true) {
  return useQuery({
    queryKey: [HUB_QUERY_KEY, 'dataset', repo.owner, repo.name, revision ?? null],
    queryFn: () => getHubDataset(repo, revision),
    enabled,
    retry: retryTransient,
    staleTime: staleTimeFor(revision),
  })
}

/** One page of rows. The previous page stays on screen while the next loads. */
export function useHubRows(repo: HubRepoRef, query: HubRowsQuery, enabled = true) {
  return useQuery({
    queryKey: [HUB_QUERY_KEY, 'rows', repo.owner, repo.name, query],
    queryFn: () => getHubRows(repo, query),
    enabled,
    retry: retryTransient,
    placeholderData: keepPreviousData,
    staleTime: staleTimeFor(query.revision),
  })
}

/** One full row, every cell uncut. */
export function useHubRow(repo: HubRepoRef, rowIdx: number | null, query: HubSplitQuery) {
  return useQuery({
    queryKey: [HUB_QUERY_KEY, 'row', repo.owner, repo.name, rowIdx, query],
    queryFn: () => getHubRow(repo, rowIdx as number, query),
    enabled: rowIdx != null,
    retry: retryTransient,
    staleTime: staleTimeFor(query.revision),
  })
}

/** Per-column statistics of a split. */
export function useHubStatistics(repo: HubRepoRef, query: HubSplitQuery, enabled = true) {
  return useQuery({
    queryKey: [HUB_QUERY_KEY, 'statistics', repo.owner, repo.name, query],
    queryFn: () => getHubStatistics(repo, query),
    enabled,
    retry: retryTransient,
    staleTime: staleTimeFor(query.revision),
  })
}

/** The dataset's versions: its commits, newest first. */
export function useHubCommits(repo: HubRepoRef, enabled = true) {
  return useQuery({
    queryKey: [HUB_QUERY_KEY, 'commits', repo.owner, repo.name],
    queryFn: () => getHubCommits(repo),
    enabled,
    retry: retryTransient,
    staleTime: 30_000,
  })
}

/** Rows added, removed and changed in a split between two versions. */
export function useHubCompare(repo: HubRepoRef, query: HubCompareQuery | null) {
  return useQuery({
    queryKey: [HUB_QUERY_KEY, 'compare', repo.owner, repo.name, query],
    queryFn: () => getHubCompare(repo, query as HubCompareQuery),
    enabled: query != null,
    retry: retryTransient,
    staleTime: Infinity,
  })
}
