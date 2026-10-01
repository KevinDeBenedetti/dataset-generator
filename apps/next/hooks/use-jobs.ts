import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { cancelJobRun, getJobRun, getJobs, publishJobRun, startJobRun } from '@/api/sdk'
import type { JobRunOut } from '@/api/types'

export const JOBS_QUERY_KEY = ['jobs']
const JOB_RUN_QUERY_KEY = 'job-run'

// The dataset job catalogue, with each job's options schema, config status
// and latest run.
export function useJobs() {
  return useQuery({
    queryKey: JOBS_QUERY_KEY,
    queryFn: getJobs,
  })
}

const ACTIVE = new Set(['queued', 'running', 'publishing'])

// One run's state, polled every 2 s while it is queued or running.
export function useJobRun(runId: string | null | undefined) {
  return useQuery({
    queryKey: [JOB_RUN_QUERY_KEY, runId],
    queryFn: () => getJobRun(runId as string),
    enabled: !!runId,
    refetchInterval: (query) => (ACTIVE.has(query.state.data?.status ?? '') ? 2000 : false),
  })
}

export function useStartJobRun(jobId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      options,
      modelRef,
    }: {
      options: Record<string, unknown>
      modelRef?: string | null
    }) => startJobRun(jobId, options, modelRef),
    onSuccess: (run: JobRunOut) => {
      queryClient.setQueryData([JOB_RUN_QUERY_KEY, run.id], run)
      queryClient.invalidateQueries({ queryKey: JOBS_QUERY_KEY })
    },
  })
}

export function usePublishJobRun(runId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (selection: { exclude: string[]; promote: string[] }) =>
      publishJobRun(runId, selection),
    onSuccess: (run: JobRunOut) => {
      queryClient.setQueryData([JOB_RUN_QUERY_KEY, run.id], run)
      queryClient.invalidateQueries({ queryKey: JOBS_QUERY_KEY })
    },
  })
}

export function useCancelJobRun(runId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => cancelJobRun(runId),
    onSuccess: (run: JobRunOut) => {
      queryClient.setQueryData([JOB_RUN_QUERY_KEY, run.id], run)
      queryClient.invalidateQueries({ queryKey: JOBS_QUERY_KEY })
    },
  })
}
