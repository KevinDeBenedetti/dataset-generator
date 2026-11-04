'use client'

import { useCallback, useMemo } from 'react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import type { HubRowFilter } from '@/api/sdk'

// The dataset page keeps what it shows in the URL (tab, revision, split,
// search, filters, page, open row, comparison) so a view can be shared,
// reloaded and walked back with the browser's history.

export type HubTab = 'data' | 'card' | 'stats' | 'files' | 'history'
export type HubLayout = 'cards' | 'table'

export interface HubViewState {
  tab: HubTab
  rev: string | null
  config: string | null
  split: string | null
  q: string
  page: number
  size: number
  sort: string | null
  order: 'asc' | 'desc'
  filters: HubRowFilter[]
  layout: HubLayout | null
  row: number | null
  base: string | null
  head: string | null
}

export const PAGE_SIZES = [25, 50, 100]
const TABS = new Set<string>(['data', 'card', 'stats', 'files', 'history'])
const OPS = new Set<string>(['eq', 'ne', 'lt', 'lte', 'gt', 'gte', 'contains', 'null', 'not_null'])

// Changing any of these shows other rows: back to the first page.
const RESETS_PAGE: (keyof HubViewState)[] = [
  'rev',
  'config',
  'split',
  'q',
  'size',
  'sort',
  'order',
  'filters',
]

function parseFilters(raw: string | null): HubRowFilter[] {
  if (!raw) return []
  try {
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter(
      (f): f is HubRowFilter =>
        typeof f === 'object' &&
        f !== null &&
        typeof (f as HubRowFilter).column === 'string' &&
        OPS.has((f as HubRowFilter).op),
    )
  } catch {
    return []
  }
}

function parseNumber(raw: string | null, fallback: number): number {
  const value = Number(raw)
  return Number.isInteger(value) && value >= 0 ? value : fallback
}

export function parseHubState(params: URLSearchParams): HubViewState {
  const tab = params.get('tab') as HubTab | null
  const size = parseNumber(params.get('size'), PAGE_SIZES[0])
  const layout = params.get('layout')
  const row = params.get('row')
  return {
    tab: tab && TABS.has(tab) ? tab : 'data',
    rev: params.get('rev') || null,
    config: params.get('config') || null,
    split: params.get('split') || null,
    q: params.get('q') ?? '',
    page: Math.max(1, parseNumber(params.get('page'), 1)),
    size: PAGE_SIZES.includes(size) ? size : PAGE_SIZES[0],
    sort: params.get('sort') || null,
    order: params.get('order') === 'desc' ? 'desc' : 'asc',
    filters: parseFilters(params.get('f')),
    layout: layout === 'cards' || layout === 'table' ? layout : null,
    row: row != null && row !== '' ? parseNumber(row, 0) : null,
    base: params.get('base') || null,
    head: params.get('head') || null,
  }
}

export function serializeHubState(state: HubViewState): string {
  const params = new URLSearchParams()
  const set = (key: string, value: string | number | null | undefined, skip?: unknown) => {
    if (value !== null && value !== undefined && value !== '' && value !== skip) {
      params.set(key, String(value))
    }
  }
  set('tab', state.tab, 'data')
  set('rev', state.rev)
  set('config', state.config)
  set('split', state.split)
  set('q', state.q)
  set('page', state.page, 1)
  set('size', state.size, PAGE_SIZES[0])
  set('sort', state.sort)
  if (state.sort) set('order', state.order, 'asc')
  if (state.filters.length) params.set('f', JSON.stringify(state.filters))
  set('layout', state.layout)
  set('row', state.row)
  set('base', state.base)
  set('head', state.head)
  return params.toString()
}

/** The next state after ``patch``: a change of rows also resets the page. */
export function applyPatch(state: HubViewState, patch: Partial<HubViewState>): HubViewState {
  const next = { ...state, ...patch }
  if (!('page' in patch) && RESETS_PAGE.some((key) => key in patch)) next.page = 1
  return next
}

export function useHubUrlState(): [HubViewState, (patch: Partial<HubViewState>) => void] {
  const router = useRouter()
  const pathname = usePathname()
  const search = useSearchParams()
  const searchText = search.toString()
  const state = useMemo(() => parseHubState(new URLSearchParams(searchText)), [searchText])

  const update = useCallback(
    (patch: Partial<HubViewState>) => {
      const query = serializeHubState(applyPatch(state, patch))
      router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false })
    },
    [router, pathname, state],
  )
  return [state, update]
}
