import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getCollections, syncCollectionToQdrant } from '@/api/sdk'

export const COLLECTIONS_QUERY_KEY = ['collections']

export function useCollections() {
  return useQuery({
    queryKey: COLLECTIONS_QUERY_KEY,
    queryFn: getCollections,
  })
}

export function useSyncCollectionToQdrant() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (datasetName: string) => syncCollectionToQdrant(datasetName),
    onSuccess: () => {
      // Refresh point counts / in-qdrant status after a sync.
      queryClient.invalidateQueries({ queryKey: COLLECTIONS_QUERY_KEY })
    },
  })
}
