'use client'

import { useState } from 'react'
import { toast } from 'sonner'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Icon } from '@/components/app/icon'
import { useCollections, useSearchCollection, useSyncCollectionToQdrant } from '@/hooks'
import { useIsAdmin } from '@/hooks/use-auth'
import type { Collection, CollectionSearchResult } from '@/api/sdk'

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
    <div className="flex flex-col gap-3 border-t pt-3">
      <div className="flex gap-2">
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') handleSearch()
          }}
          placeholder="Search this collection…"
          aria-label={`Search ${datasetName}`}
        />
        <Button size="sm" onClick={handleSearch} disabled={search.isPending || !query.trim()}>
          {search.isPending ? (
            <Icon name="loader" className="animate-spin" />
          ) : (
            <Icon name="search" />
          )}
        </Button>
      </div>

      {search.isSuccess && results.length === 0 && (
        <p className="text-xs text-muted-foreground">No matches found.</p>
      )}

      {results.length > 0 && (
        <ul className="flex flex-col gap-2">
          {results.map((r, i) => (
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

function CollectionCard({
  collection,
  qdrantConfigured,
}: {
  collection: Collection
  qdrantConfigured: boolean
}) {
  const sync = useSyncCollectionToQdrant()
  const isAdmin = useIsAdmin()
  const [showSearch, setShowSearch] = useState(false)

  const handleSync = async () => {
    try {
      const result = await sync.mutateAsync(collection.name)
      toast.success(`Added ${result.points_upserted} item(s) to "${result.collection_name}".`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to add collection to Qdrant')
    }
  }

  const qaCount = collection.qa_sources_count ?? 0
  const inQdrant = collection.in_qdrant === true

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="truncate">{collection.name}</CardTitle>
            <CardDescription className="truncate font-mono text-xs">
              {collection.collection_name}
            </CardDescription>
          </div>
          {qdrantConfigured && inQdrant && (
            <Badge variant="secondary" className="shrink-0">
              <Icon name="check" />
              In Qdrant
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1">
            <Icon name="database" />
            {qaCount} Q/A pair{qaCount === 1 ? '' : 's'}
          </span>
          {collection.target_language && (
            <span className="inline-flex items-center gap-1">
              <Icon name="languages" />
              {collection.target_language}
            </span>
          )}
          {qdrantConfigured && inQdrant && collection.points_count != null && (
            <span className="inline-flex items-center gap-1">
              <Icon name="layers" />
              {collection.points_count} vector(s)
            </span>
          )}
        </div>
        {/* Syncing to Qdrant is admin-only (POST /collections/{id}/qdrant is
            require_admin). Non-admins can still browse and search. */}
        {isAdmin && (
          <Button
            size="sm"
            variant={inQdrant ? 'outline' : 'default'}
            onClick={handleSync}
            disabled={!qdrantConfigured || sync.isPending || qaCount === 0}
            className="w-full"
          >
            {sync.isPending ? (
              <>
                <Icon name="loader" className="animate-spin" />
                Adding…
              </>
            ) : (
              <>
                <Icon name="upload" />
                {inQdrant ? 'Re-sync to Qdrant' : 'Add to Qdrant'}
              </>
            )}
          </Button>
        )}

        {/* Semantic search is only possible once the collection lives in Qdrant. */}
        {qdrantConfigured && inQdrant && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setShowSearch((v) => !v)}
            className="w-full"
          >
            <Icon name="search" />
            {showSearch ? 'Hide search' : 'Search'}
          </Button>
        )}

        {qdrantConfigured && inQdrant && showSearch && (
          <SearchPanel datasetName={collection.name} />
        )}
      </CardContent>
    </Card>
  )
}

export default function CollectionsPage() {
  const { data, isLoading, error } = useCollections()
  const collections = data?.collections ?? []
  const qdrantConfigured = data?.qdrant_configured ?? false

  return (
    <section className="mx-auto w-full max-w-5xl px-4 py-10">
      <header className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight">Collections</h1>
        <p className="text-muted-foreground">
          Your datasets, ready to be embedded into a Qdrant vector store for semantic search and
          retrieval.
        </p>
      </header>

      {!isLoading && !qdrantConfigured && (
        <div className="mb-6 rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
          <p className="font-medium text-foreground">Qdrant is not configured.</p>
          <p className="mt-1">
            Set <code>QDRANT_URL</code> (and optionally <code>QDRANT_API_KEY</code>) in your{' '}
            <code>.env</code> to enable pushing collections to Qdrant. Datasets are still listed
            below.
          </p>
        </div>
      )}

      {isLoading && <p className="py-12 text-center text-muted-foreground">Loading collections…</p>}

      {!isLoading && error && (
        <p className="py-12 text-center text-destructive">
          {error instanceof Error ? error.message : 'Failed to load collections'}
        </p>
      )}

      {!isLoading && !error && collections.length === 0 && (
        <div className="py-12 text-center text-muted-foreground">
          <p>No collections yet.</p>
          <p className="mt-1 text-sm">
            Generate a dataset first — it will appear here as a collection.
          </p>
        </div>
      )}

      {!isLoading && !error && collections.length > 0 && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {collections.map((collection) => (
            <CollectionCard
              key={collection.id}
              collection={collection}
              qdrantConfigured={qdrantConfigured}
            />
          ))}
        </div>
      )}
    </section>
  )
}
