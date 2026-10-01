import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { adminApi } from '@/api/sdk'

const ADMIN_KEY = ['admin']

export function useAdminUsers(q: string, offset: number) {
  return useQuery({
    queryKey: [...ADMIN_KEY, 'users', q, offset],
    queryFn: () => adminApi.users(q, offset),
    placeholderData: keepPreviousData,
  })
}

export function useUpdateAdminUser() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (v: { id: string; role?: 'user' | 'admin'; is_active?: boolean }) =>
      adminApi.updateUser(v.id, { role: v.role, is_active: v.is_active }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ADMIN_KEY }),
  })
}

export function useDeleteAdminUser() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => adminApi.deleteUser(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ADMIN_KEY }),
  })
}

export function useAuditLog(offset: number, action: string) {
  return useQuery({
    queryKey: [...ADMIN_KEY, 'audit', offset, action],
    queryFn: () => adminApi.audit(offset, action),
    placeholderData: keepPreviousData,
  })
}

export function useAdminUsage() {
  return useQuery({ queryKey: [...ADMIN_KEY, 'usage'], queryFn: adminApi.usage })
}

export function usePlatform() {
  return useQuery({ queryKey: [...ADMIN_KEY, 'platform'], queryFn: adminApi.platform })
}

export function useUpdatePlatform() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: adminApi.updatePlatform,
    onSuccess: (data) => queryClient.setQueryData([...ADMIN_KEY, 'platform'], data),
  })
}
