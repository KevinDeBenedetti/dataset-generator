import { useQuery } from '@tanstack/react-query'
import {
  errorStatus,
  getGitHubDoc,
  getGitHubProfile,
  getGitHubRepo,
  getGitHubRepos,
} from '@/api/sdk'

export const GITHUB_QUERY_KEY = 'github'

// No username, not found, rate limited: asking again changes nothing.
const DEFINITIVE = new Set([400, 401, 403, 404, 429])

// Typed on Error: React Query infers each query's error type from it.
function retryTransient(failureCount: number, error: Error): boolean {
  const status = errorStatus(error)
  return !(status != null && DEFINITIVE.has(status)) && failureCount < 2
}

// The server caches GitHub answers for 5 minutes: no point asking sooner.
const STALE = 5 * 60_000

/** Your GitHub account and what is left of the API quota. */
export function useGitHubProfile() {
  return useQuery({
    queryKey: [GITHUB_QUERY_KEY, 'profile'],
    queryFn: getGitHubProfile,
    retry: retryTransient,
    staleTime: 60_000,
  })
}

/** Your public repos, most recently updated first. */
export function useGitHubRepos() {
  return useQuery({
    queryKey: [GITHUB_QUERY_KEY, 'repos'],
    queryFn: getGitHubRepos,
    retry: retryTransient,
    staleTime: STALE,
  })
}

/** One repo as a generation sees it. */
export function useGitHubRepo(owner: string | null, repo: string | null) {
  return useQuery({
    queryKey: [GITHUB_QUERY_KEY, 'repo', owner, repo],
    queryFn: () => getGitHubRepo(owner as string, repo as string),
    enabled: !!owner && !!repo,
    retry: retryTransient,
    staleTime: STALE,
  })
}

/** One docs/ file, as the model reads it. */
export function useGitHubDoc(owner: string | null, repo: string | null, path: string | null) {
  return useQuery({
    queryKey: [GITHUB_QUERY_KEY, 'doc', owner, repo, path],
    queryFn: () => getGitHubDoc(owner as string, repo as string, path as string),
    enabled: !!owner && !!repo && !!path,
    retry: retryTransient,
    staleTime: STALE,
  })
}
