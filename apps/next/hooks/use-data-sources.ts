import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { RecipeScheduleIn } from '@/api/gen/types.gen'
import {
  getSourceRecipeSchedule,
  saveSourceRecipeSchedule,
  createDataSource,
  updateDataSource,
  discoverConnector,
  getDatagouvProfile,
  createSourceRecipe,
  deleteDataSource,
  deleteSourceRecipe,
  getSourceRecipe,
  listConnectors,
  listDataSources,
  listRecipeRuns,
  listSourceRecipes,
  previewSourceRecipe,
  runSourceRecipe,
  updateSourceRecipe,
  uploadDataSource,
  type RecipeStep,
  type SourceRecipe,
  type UploadSourceParams,
} from '@/api/sdk'

const SOURCES = ['data-sources']
const RECIPES = ['recipes']
const RUNS = ['runs']

export function useConnectors() {
  return useQuery({ queryKey: ['connectors'], queryFn: listConnectors, staleTime: 300_000 })
}

export function useDataSources() {
  return useQuery({ queryKey: SOURCES, queryFn: listDataSources })
}

export function useUploadDataSource() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      params,
      onProgress,
    }: {
      params: UploadSourceParams
      onProgress?: (done: number, total: number) => void
    }) => uploadDataSource(params, onProgress),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: SOURCES }),
  })
}

export function useDeleteDataSource() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteDataSource,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: SOURCES })
      void queryClient.invalidateQueries({ queryKey: RECIPES })
    },
  })
}

export function useRecipes() {
  return useQuery({ queryKey: RECIPES, queryFn: listSourceRecipes })
}

export function useRecipe(id: string) {
  return useQuery({ queryKey: [...RECIPES, id], queryFn: () => getSourceRecipe(id) })
}

export function useCreateRecipe() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createSourceRecipe,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: RECIPES }),
  })
}

export function useUpdateRecipe(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Partial<SourceRecipe>) => updateSourceRecipe(id, body),
    onSuccess: (saved) => {
      queryClient.setQueryData([...RECIPES, id], saved)
      void queryClient.invalidateQueries({ queryKey: RECIPES, exact: true })
    },
  })
}

export function useDeleteRecipe() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteSourceRecipe,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: RECIPES }),
  })
}

// The preview of `steps` (debounced by the caller through `steps`' identity).
export function useRecipePreview(id: string, steps: RecipeStep[] | null) {
  return useQuery({
    queryKey: [...RECIPES, id, 'preview', steps],
    queryFn: () => previewSourceRecipe(id, steps ?? undefined),
    enabled: steps !== null,
    retry: false,
    placeholderData: (previous) => previous,
  })
}

export function useRunRecipe(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => runSourceRecipe(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: RUNS }),
  })
}

export function useRecipeRuns() {
  return useQuery({ queryKey: RUNS, queryFn: listRecipeRuns, refetchInterval: 5000 })
}

export function useDiscover(kind: string, q: string) {
  return useQuery({
    queryKey: ['connectors', kind, 'discover', q],
    queryFn: () => discoverConnector(kind, q),
    enabled: q.trim().length >= 2,
    staleTime: 60_000,
    retry: false,
  })
}

export function useDatagouvProfile(resourceId: string | null) {
  return useQuery({
    queryKey: ['connectors', 'datagouv', 'profile', resourceId],
    queryFn: () => getDatagouvProfile(resourceId as string),
    enabled: !!resourceId,
    retry: false,
  })
}

export function useUpdateDataSource(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Parameters<typeof updateDataSource>[1]) => updateDataSource(id, body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: SOURCES }),
  })
}

export function useCreateDataSource() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createDataSource,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: SOURCES }),
  })
}

export function useSourceRecipeSchedule(id: string) {
  return useQuery({
    queryKey: [...RECIPES, id, 'schedule'],
    queryFn: () => getSourceRecipeSchedule(id),
  })
}

export function useSaveSourceRecipeSchedule(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (schedule: RecipeScheduleIn | null) => saveSourceRecipeSchedule(id, schedule),
    onSuccess: (saved) => queryClient.setQueryData([...RECIPES, id, 'schedule'], saved),
  })
}
