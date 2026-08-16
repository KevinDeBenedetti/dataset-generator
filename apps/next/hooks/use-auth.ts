import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { login, logout, getCurrentUser, type AuthUser } from '@/api/sdk'

export const CURRENT_USER_QUERY_KEY = ['auth', 'me']

// Where to land after login: the `?from=` deep-link the proxy set when it
// bounced an unauthenticated request, falling back to /dashboard. Read from the
// live URL (login runs client-side only) so we don't need a useSearchParams
// Suspense boundary. Only same-origin absolute paths are honoured — protocol-
// relative (`//evil`) and absolute URLs are rejected to avoid open redirects.
function postLoginRedirect(): string {
  if (typeof window === 'undefined') return '/dashboard'
  const from = new URLSearchParams(window.location.search).get('from')
  if (from && from.startsWith('/') && !from.startsWith('//')) return from
  return '/dashboard'
}

// Current authenticated user (null when not logged in). Cached and shared.
export function useCurrentUser() {
  return useQuery<AuthUser | null>({
    queryKey: CURRENT_USER_QUERY_KEY,
    queryFn: getCurrentUser,
    staleTime: 60_000,
    // A 401 resolves to null (not an error), so any thrown error is a transient
    // failure (5xx / network) — retry a couple of times instead of dropping the
    // user to a logged-out state on a blip.
    retry: 2,
  })
}

// Convenience flag for gating admin-only UI. Resolves false until the current
// user is known (and for non-admins), so admin-only controls stay hidden by
// default rather than flashing in before the role loads.
export function useIsAdmin(): boolean {
  const { data: user } = useCurrentUser()
  return user?.role === 'admin'
}

export function useLogin() {
  const queryClient = useQueryClient()
  const router = useRouter()

  return useMutation({
    mutationFn: ({ email, password }: { email: string; password: string }) =>
      login(email, password),
    onSuccess: (user) => {
      queryClient.setQueryData(CURRENT_USER_QUERY_KEY, user)
      router.replace(postLoginRedirect())
      router.refresh()
    },
  })
}

export function useLogout() {
  const queryClient = useQueryClient()
  const router = useRouter()

  return useMutation({
    mutationFn: logout,
    onSuccess: () => {
      queryClient.setQueryData(CURRENT_USER_QUERY_KEY, null)
      queryClient.clear()
      router.replace('/login')
      router.refresh()
    },
  })
}
