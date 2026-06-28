'use client'

import { toast } from 'sonner'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/app/icon'
import { useCollections, useSyncCollectionToQdrant } from '@/hooks'
import type { Collection } from '@/api/sdk'

function CollectionCard({
  collection,
  qdrantConfigured,
}: {
  collection: Collection
  qdrantConfigured: boolean
}) {
  const sync = useSyncCollectionToQdrant()

  const handleSync = async () => {
    try {
      const result = await sync.mutateAsync(collection.name)
      toast.success(
        `Added ${result.points_upserted} item(s) to "${result.collection_name}".`
      )
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : 'Failed to add collection to Qdrant'
      )
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
          Your datasets, ready to be embedded into a Qdrant vector store for
          semantic search and retrieval.
        </p>
      </header>

      {!isLoading && !qdrantConfigured && (
        <div className="mb-6 rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
          <p className="font-medium text-foreground">Qdrant is not configured.</p>
          <p className="mt-1">
            Set <code>QDRANT_URL</code> (and optionally <code>QDRANT_API_KEY</code>)
            in your <code>.env</code> to enable pushing collections to Qdrant.
            Datasets are still listed below.
          </p>
        </div>
      )}

      {isLoading && (
        <p className="py-12 text-center text-muted-foreground">Loading collections…</p>
      )}

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
