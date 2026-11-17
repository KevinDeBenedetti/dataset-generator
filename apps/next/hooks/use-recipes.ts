import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createRecipe,
  deleteRecipe,
  deleteRecipeSchedule,
  getRecipeSchedule,
  getRecipes,
  runRecipe,
  saveRecipeSchedule,
  updateRecipe,
} from '@/api/sdk'
import type {
  JobRunOut,
  RecipeIn,
  RecipeOut,
  RecipeRunRequest,
  RecipeScheduleIn,
  RecipeScheduleOut,
  RecipesOut,
} from '@/api/types'
import { JOB_RUN_QUERY_KEY } from './use-jobs'

export const RECIPES_QUERY_KEY = ['recipes']

/** Your dataset recipes, most recently edited first. */
export function useRecipes() {
  return useQuery({ queryKey: RECIPES_QUERY_KEY, queryFn: getRecipes })
}

function upsert(list: RecipesOut | undefined, recipe: RecipeOut): RecipesOut {
  const others = (list?.recipes ?? []).filter((r) => r.id !== recipe.id)
  return { recipes: [recipe, ...others] }
}

export function useCreateRecipe() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (recipe: RecipeIn) => createRecipe(recipe),
    onSuccess: (recipe) => {
      queryClient.setQueryData<RecipesOut>(RECIPES_QUERY_KEY, (list) => upsert(list, recipe))
    },
  })
}

/** Saves the whole recipe; the page shows the change at once and reverts it
 * if the server refuses. */
export function useUpdateRecipe() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, recipe }: { id: string; recipe: RecipeIn }) => updateRecipe(id, recipe),
    onMutate: async ({ id, recipe }) => {
      await queryClient.cancelQueries({ queryKey: RECIPES_QUERY_KEY })
      const before = queryClient.getQueryData<RecipesOut>(RECIPES_QUERY_KEY)
      queryClient.setQueryData<RecipesOut>(RECIPES_QUERY_KEY, (list) =>
        list ? { recipes: list.recipes.map((r) => (r.id === id ? { ...r, ...recipe } : r)) } : list,
      )
      return { before }
    },
    onError: (_error, _vars, context) => {
      if (context?.before) queryClient.setQueryData(RECIPES_QUERY_KEY, context.before)
    },
    onSuccess: (recipe) => {
      queryClient.setQueryData<RecipesOut>(RECIPES_QUERY_KEY, (list) =>
        list ? { recipes: list.recipes.map((r) => (r.id === recipe.id ? recipe : r)) } : list,
      )
    },
  })
}

export function useDeleteRecipe() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => deleteRecipe(id),
    onSuccess: (_result, id) => {
      queryClient.setQueryData<RecipesOut>(RECIPES_QUERY_KEY, (list) =>
        list ? { recipes: list.recipes.filter((r) => r.id !== id) } : list,
      )
    },
  })
}

/** Queues a generation of the recipe; the run is then polled with useJobRun. */
export function useRunRecipe() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, request }: { id: string; request?: RecipeRunRequest }) =>
      runRecipe(id, request),
    onSuccess: (run: JobRunOut, { id }) => {
      queryClient.setQueryData([JOB_RUN_QUERY_KEY, run.id], run)
      queryClient.setQueryData<RecipesOut>(RECIPES_QUERY_KEY, (list) =>
        list
          ? {
              recipes: list.recipes.map((r) =>
                r.id === id ? { ...r, latest_run: { id: run.id, status: run.status } } : r,
              ),
            }
          : list,
      )
    },
  })
}

const scheduleKey = (id: string) => [...RECIPES_QUERY_KEY, id, 'schedule']

/** When the recipe regenerates by itself; null when it has no schedule. */
export function useRecipeSchedule(id: string) {
  return useQuery({ queryKey: scheduleKey(id), queryFn: () => getRecipeSchedule(id) })
}

/** Saves the schedule, or removes it when `schedule` is null. */
export function useSaveRecipeSchedule(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (schedule: RecipeScheduleIn | null): Promise<RecipeScheduleOut | null> => {
      if (schedule) return saveRecipeSchedule(id, schedule)
      await deleteRecipeSchedule(id)
      return null
    },
    onSuccess: (saved) => queryClient.setQueryData(scheduleKey(id), saved),
  })
}
