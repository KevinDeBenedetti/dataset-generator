import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { login, logout, getCurrentUser, type AuthUser } from '@/api/sdk'

export const CURRENT_USER_QUERY_KEY = ['auth', 'me']

// Current authenticated user (null when not logged in). Cached and shared.
export function useCurrentUser() {
  return useQuery<AuthUser | null>({
    queryKey: CURRENT_USER_QUERY_KEY,
    queryFn: getCurrentUser,
    staleTime: 60_000,
    retry: false,
  })
}

export function useLogin() {
  const queryClient = useQueryClient()
  const router = useRouter()

  return useMutation({
    mutationFn: ({ email, password }: { email: string; password: string }) =>
      login(email, password),
    onSuccess: (user) => {
      queryClient.setQueryData(CURRENT_USER_QUERY_KEY, user)
      router.replace('/dashboard')
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
