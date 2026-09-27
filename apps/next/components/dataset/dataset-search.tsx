'use client'

import { useState } from 'react'
import { toast } from 'sonner'
import { Icon } from '@/components/app/icon'
import { useCollections, useSearchCollection, useSyncCollectionToQdrant } from '@/hooks'
import { useIsAdmin } from '@/hooks/use-auth'
import type { CollectionSearchResult } from '@/api/sdk'

function SearchPanel({ datasetName }: { datasetName: string }) {
  const [query, setQuery] = useState('')
  const search = useSearchCollection()
  const results: CollectionSearchResult[] = search.data?.results ?? []

  const handleSearch = async () => {
    const q = query.trim()
    if (!q) return
    try {
      await search.mutateAsync({ datasetName, query: q })
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to search collection')
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div style={{ display: 'flex', gap: 8 }}>
        <input
          className="input"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') handleSearch()
          }}
          placeholder="Search this dataset semantically…"
          aria-label={`Search ${datasetName}`}
        />
        <button
          type="button"
          className="btn btn-outline"
          onClick={handleSearch}
          disabled={search.isPending || !query.trim()}
        >
          <Icon
            name={search.isPending ? 'loader' : 'search'}
            className={search.isPending ? 'animate-spin' : undefined}
          />
        </button>
      </div>

      {search.isSuccess && results.length === 0 && <p className="hint">No matches found.</p>}

      {results.length > 0 && (
        <ul className="flex flex-col gap-2">
          {results.map((r, i) => (
            // oxlint-disable-next-line react/no-array-index-key -- qa_id is
            // optional on a hit; the index only breaks ties among same-id rows.
            <li key={r.qa_id ?? i} className="rounded-md border bg-muted/30 p-2 text-xs">
              <div className="flex items-start justify-between gap-2">
                <p className="font-medium text-foreground">{r.question}</p>
                {r.score != null && (
                  <span className="shrink-0 font-mono text-muted-foreground">
                    {r.score.toFixed(3)}
                  </span>
                )}
              </div>
              <p className="mt-1 line-clamp-3 text-muted-foreground">{r.answer}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// The Qdrant sync + semantic search actions for one dataset, shown as the
// detail page's "Search" tab. Collections used to be a separate page listing
// every dataset a second time just to expose this — folded in here instead,
// since it's a per-dataset action, not a distinct browsable resource.
export function DatasetSearch({ datasetName }: { datasetName: string }) {
  const { data, isPending } = useCollections()
  const collection = data?.collections.find((c) => c.name === datasetName) ?? null
  const qdrantConfigured = data?.qdrant_configured ?? false
  const inQdrant = collection?.in_qdrant === true
  const qaCount = collection?.qa_sources_count ?? 0

  const isAdmin = useIsAdmin()
  const sync = useSyncCollectionToQdrant()
  const [showSearch, setShowSearch] = useState(false)

  const handleSync = async () => {
    try {
      const result = await sync.mutateAsync(datasetName)
      toast.success(`Added ${result.points_upserted} item(s) to "${result.collection_name}".`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to add dataset to Qdrant')
    }
  }

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <div className="card-title">Vector search</div>
          <div className="card-desc">
            Sync this dataset into Qdrant to search its Q/A pairs semantically.
          </div>
        </div>
        {qdrantConfigured && inQdrant && (
          <span className="badge badge-success">
            <span className="dot" />
            In Qdrant
            {collection?.points_count != null && ` · ${collection.points_count} vector(s)`}
          </span>
        )}
      </div>

      <div
        className="card-body"
        style={{ paddingTop: 0, display: 'flex', flexDirection: 'column', gap: 14 }}
      >
        {isPending && <p className="muted">Loading Qdrant status…</p>}

        {!isPending && !qdrantConfigured && (
          <p className="hint">
            Qdrant is not configured. Set <code>QDRANT_URL</code> (and optionally{' '}
            <code>QDRANT_API_KEY</code>) to enable syncing and search.
          </p>
        )}

        {/* Syncing is admin-only (POST /collections/{id}/qdrant is
            require_admin) — non-admins can still search once it's synced. */}
        {!isPending && qdrantConfigured && isAdmin && (
          <button
            type="button"
            className="btn btn-outline"
            onClick={handleSync}
            disabled={sync.isPending || qaCount === 0}
            style={{ alignSelf: 'flex-start' }}
          >
            <Icon
              name={sync.isPending ? 'loader' : 'upload'}
              className={sync.isPending ? 'animate-spin' : undefined}
            />
            {sync.isPending ? 'Adding…' : inQdrant ? 'Re-sync to Qdrant' : 'Add to Qdrant'}
          </button>
        )}

        {!isPending && qdrantConfigured && inQdrant && (
          <>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => setShowSearch((v) => !v)}
              style={{ alignSelf: 'flex-start' }}
            >
              <Icon name="search" />
              {showSearch ? 'Hide search' : 'Search'}
            </button>
            {showSearch && <SearchPanel datasetName={datasetName} />}
          </>
        )}
      </div>
    </div>
  )
}
