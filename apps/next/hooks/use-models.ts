import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getModels, testModel, updateModelDefaults } from '@/api/sdk'
import type { ModelsResponse } from '@/api/types'

export const MODELS_QUERY_KEY = ['models']

// Providers, models and role defaults. `discover` (the Models page) also
// lists the models the OpenAI-compatible endpoint serves — a network call —
// while pickers elsewhere make do with the configured ones.
export function useModels(discover = false) {
  return useQuery({
    queryKey: [...MODELS_QUERY_KEY, { discover }],
    queryFn: () => getModels(discover),
    staleTime: 60_000,
  })
}

export function useUpdateModelDefaults() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (defaults: Record<string, string>) => updateModelDefaults(defaults),
    onSuccess: (data: ModelsResponse) => {
      queryClient.setQueryData([...MODELS_QUERY_KEY, { discover: false }], data)
      queryClient.invalidateQueries({ queryKey: MODELS_QUERY_KEY })
    },
  })
}

export function useTestModel() {
  return useMutation({ mutationFn: (ref: string) => testModel(ref) })
}
