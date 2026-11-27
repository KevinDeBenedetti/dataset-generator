import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  appendRecipeStep,
  getDraftRows,
  getTabularDraft,
  reviewTabularDraft,
  type DraftRowsQuery,
} from '@/api/sdk'

export const tabularDraftKey = (runId: string) => ['runs', runId, 'draft']

export function useTabularDraft(runId: string) {
  return useQuery({ queryKey: tabularDraftKey(runId), queryFn: () => getTabularDraft(runId) })
}

export function useDraftRows(runId: string, query: DraftRowsQuery) {
  return useQuery({
    queryKey: [...tabularDraftKey(runId), 'rows', query],
    queryFn: () => getDraftRows(runId, query),
    placeholderData: keepPreviousData,
  })
}

export function useReviewDraft(runId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ decision, comment }: { decision: 'approved' | 'rejected'; comment?: string }) =>
      reviewTabularDraft(runId, decision, comment),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: tabularDraftKey(runId) }),
  })
}

export function useSaveRecipeSteps() {
  return useMutation({
    mutationFn: ({ recipeId, steps }: { recipeId: string; steps: Record<string, unknown>[] }) =>
      appendRecipeStep(recipeId, steps),
  })
}
