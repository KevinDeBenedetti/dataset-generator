import { useQuery } from '@tanstack/react-query'
import { errorStatus, getResume, getResumes } from '@/api/sdk'

export const RESUME_QUERY_KEY = 'resumes'

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
