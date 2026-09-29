import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  getJobsStatus,
  triggerCorpusSync,
  triggerQADatasetSync,
  type CorpusSource,
} from '@/api/sdk'

export const JOBS_STATUS_QUERY_KEY = ['jobs-status']

export function useJobsStatus() {
  return useQuery({
    queryKey: JOBS_STATUS_QUERY_KEY,
    queryFn: getJobsStatus,
  })
}

export function useTriggerCorpusSync() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (options?: { sources?: CorpusSource[]; dryRun?: boolean }) =>
      triggerCorpusSync(options),
    // A successful (non-dry-run) publish may flip what's "configured" — e.g.
    // the first run creates the Hub repo — so the status card stays current.
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: JOBS_STATUS_QUERY_KEY })
    },
  })
}

export function useTriggerQADatasetSync() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (options?: { maxRepos?: number; dryRun?: boolean }) =>
      triggerQADatasetSync(options),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: JOBS_STATUS_QUERY_KEY })
    },
  })
}
