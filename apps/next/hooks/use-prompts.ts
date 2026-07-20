import { useQuery } from '@tanstack/react-query'
import { getPrompts } from '@/api/sdk'

export const PROMPTS_QUERY_KEY = ['prompts']

// The app's real LLM prompts (read-only; they live in the server codebase).
export function usePrompts() {
  return useQuery({
    queryKey: PROMPTS_QUERY_KEY,
    queryFn: getPrompts,
    // Prompts only change with a deploy — no point refetching aggressively.
    staleTime: Infinity,
  })
}
