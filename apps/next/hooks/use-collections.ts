import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createCollection,
  deleteCollection,
  evaluateCollection,
  getCollection,
  getCollections,
  rebuildCollection,
  searchCollection,
} from '@/api/sdk'
import type {
  CollectionCreate,
  CollectionEvaluateRequest,
  CollectionEvaluation,
  CollectionOut,
  CollectionSearchRequest,
  CollectionsOut,
} from '@/api/types'

export const COLLECTIONS_QUERY_KEY = ['collections']

// A build is a worker run: while one is going, its progress is polled.
const POLL_MS = 2000

/** Your collections, with the models a new one can use. Polled while one of
 * them is being built. */
export function useCollections() {
  return useQuery({
    queryKey: COLLECTIONS_QUERY_KEY,
    queryFn: getCollections,
    refetchInterval: (query) =>
      query.state.data?.collections.some((c) => c.status === 'building') ? POLL_MS : false,
  })
}

/** One collection, polled while it is being built. */
export function useCollection(id: string) {
  return useQuery({
    queryKey: [...COLLECTIONS_QUERY_KEY, id],
    queryFn: () => getCollection(id),
    refetchInterval: (query) => (query.state.data?.status === 'building' ? POLL_MS : false),
  })
}

function store(queryClient: ReturnType<typeof useQueryClient>, collection: CollectionOut) {
  queryClient.setQueryData([...COLLECTIONS_QUERY_KEY, collection.id], collection)
  queryClient.setQueryData<CollectionsOut>(COLLECTIONS_QUERY_KEY, (list) =>
    list
      ? {
          ...list,
          collections: [collection, ...list.collections.filter((c) => c.id !== collection.id)],
        }
      : list,
  )
}

export function useCreateCollection() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: CollectionCreate) => createCollection(body),
    onSuccess: (collection) => store(queryClient, collection),
  })
}

export function useRebuildCollection(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (revision?: string | null) => rebuildCollection(id, { revision }),
    onSuccess: (collection) => store(queryClient, collection),
  })
}

export function useDeleteCollection() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => deleteCollection(id),
    onSuccess: (_result, id) => {
      queryClient.removeQueries({ queryKey: [...COLLECTIONS_QUERY_KEY, id] })
      queryClient.setQueryData<CollectionsOut>(COLLECTIONS_QUERY_KEY, (list) =>
        list ? { ...list, collections: list.collections.filter((c) => c.id !== id) } : list,
      )
    },
  })
}

export function useSearchCollection(id: string) {
  return useMutation({
    mutationFn: (body: CollectionSearchRequest) => searchCollection(id, body),
  })
}

/** Runs the retrieval test; the result is saved on the collection too. */
export function useEvaluateCollection(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: CollectionEvaluateRequest) => evaluateCollection(id, body),
    onSuccess: (evaluation: CollectionEvaluation) => {
      queryClient.setQueryData<CollectionOut>([...COLLECTIONS_QUERY_KEY, id], (c) =>
        c ? { ...c, evaluation } : c,
      )
      queryClient.invalidateQueries({ queryKey: COLLECTIONS_QUERY_KEY, exact: true })
    },
  })
}
