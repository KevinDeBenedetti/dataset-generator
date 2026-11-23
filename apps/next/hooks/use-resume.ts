import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  deleteResumeDataset,
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

/** Every resume the server's Reactive Resume key can read, newest change first. */
export function useResumes() {
  return useQuery({
    queryKey: [RESUME_QUERY_KEY],
    queryFn: getResumes,
    staleTime: 60_000,
  })
}

/** One resume, its rich text as plain text. */
export function useResume(id: string | null) {
  return useQuery({
    queryKey: [RESUME_QUERY_KEY, id],
    queryFn: () => getResume(id as string),
    enabled: !!id,
    staleTime: 60_000,
  })
}

/** The resume's dataset settings; null until saved. */
export function useResumeDataset(id: string) {
  return useQuery({
    queryKey: [DATASET_QUERY_KEY, id],
    queryFn: () => getResumeDataset(id),
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
