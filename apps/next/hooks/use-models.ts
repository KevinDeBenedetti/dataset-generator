import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getModels, testModel, updateDefaultModel } from '@/api/sdk'
import type { ModelsResponse } from '@/api/types'

export const MODELS_QUERY_KEY = ['models']

// The provider, its models, your LLM and the embedding model. `discover` (the
// Models page) also lists the models the OpenAI-compatible endpoint serves — a
// network call — while pickers elsewhere make do with the configured ones.
export function useModels(discover = false) {
  return useQuery({
    queryKey: [...MODELS_QUERY_KEY, { discover }],
    queryFn: () => getModels(discover),
    staleTime: 60_000,
  })
}

export function useUpdateDefaultModel() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (model: string) => updateDefaultModel(model),
    onSuccess: (data: ModelsResponse) => {
      queryClient.setQueryData([...MODELS_QUERY_KEY, { discover: false }], data)
      queryClient.invalidateQueries({ queryKey: MODELS_QUERY_KEY })
    },
  })
}

export function useTestModel() {
  return useMutation({ mutationFn: (ref: string) => testModel(ref) })
}
