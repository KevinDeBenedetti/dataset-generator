import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  deleteResumeDataset,
  errorStatus,
  getResume,
  getResumeDataset,
  getResumes,
  runResumeDataset,
  saveResumeDataset,
} from '@/api/sdk'
import type { JobRunOut, ResumeDatasetIn, ResumeDatasetOut } from '@/api/types'
import { DRAFTS_QUERY_KEY, JOB_RUN_QUERY_KEY } from './use-jobs'

export const RESUME_QUERY_KEY = 'resumes'
const DATASET_QUERY_KEY = 'resume-dataset'

// Not set up, not an admin, no such resume: asking again changes nothing.
const DEFINITIVE = new Set([400, 401, 403, 404])

// Typed on Error: React Query infers each query's error type from it.
function retryTransient(failureCount: number, error: Error): boolean {
  const status = errorStatus(error)
  return !(status != null && DEFINITIVE.has(status)) && failureCount < 2
}

/** Every resume the server's Reactive Resume key can read, newest change first. */
export function useResumes() {
  return useQuery({
    queryKey: [RESUME_QUERY_KEY],
    queryFn: getResumes,
    retry: retryTransient,
    staleTime: 60_000,
  })
}

/** One resume, its rich text as plain text. */
export function useResume(id: string | null) {
  return useQuery({
    queryKey: [RESUME_QUERY_KEY, id],
    queryFn: () => getResume(id as string),
    enabled: !!id,
    retry: retryTransient,
    staleTime: 60_000,
  })
}

/** The resume's dataset settings; null until saved. */
export function useResumeDataset(id: string) {
  return useQuery({
    queryKey: [DATASET_QUERY_KEY, id],
    queryFn: () => getResumeDataset(id),
    retry: retryTransient,
  })
}

export function useSaveResumeDataset(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (settings: ResumeDatasetIn) => saveResumeDataset(id, settings),
    onSuccess: (saved: ResumeDatasetOut) => {
      queryClient.setQueryData([DATASET_QUERY_KEY, id], saved)
    },
  })
}

export function useDeleteResumeDataset(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => deleteResumeDataset(id),
    onSuccess: () => {
      queryClient.setQueryData([DATASET_QUERY_KEY, id], null)
    },
  })
}

export function useRunResumeDataset(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (fullRefresh: boolean) => runResumeDataset(id, { full_refresh: fullRefresh }),
    onSuccess: (run: JobRunOut) => {
      queryClient.setQueryData([JOB_RUN_QUERY_KEY, run.id], run)
      queryClient.invalidateQueries({ queryKey: [DATASET_QUERY_KEY, id] })
      queryClient.invalidateQueries({ queryKey: DRAFTS_QUERY_KEY })
    },
  })
}
