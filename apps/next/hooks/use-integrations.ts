import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  deleteSecret,
  getSecrets,
  getSettings,
  saveSecret,
  saveSettings,
  testSecret,
  type SecretKind,
  type SettingKey,
} from '@/api/sdk'
import { MODELS_QUERY_KEY } from './use-models'
import { JOBS_QUERY_KEY } from './use-jobs'

export const SECRETS_QUERY_KEY = ['me', 'secrets']
export const SETTINGS_QUERY_KEY = ['me', 'settings']

// What is configured changes what the Models and Jobs pages can offer.
function useRefreshDependents() {
  const queryClient = useQueryClient()
  return () => {
    queryClient.invalidateQueries({ queryKey: SECRETS_QUERY_KEY })
    queryClient.invalidateQueries({ queryKey: MODELS_QUERY_KEY })
    queryClient.invalidateQueries({ queryKey: JOBS_QUERY_KEY })
  }
}

export function useSecrets() {
  return useQuery({ queryKey: SECRETS_QUERY_KEY, queryFn: getSecrets })
}

export function useSaveSecret() {
  const refresh = useRefreshDependents()
  return useMutation({
    mutationFn: (v: { kind: SecretKind; value: string; force?: boolean }) =>
      saveSecret(v.kind, v.value, v.force),
    onSuccess: refresh,
  })
}

export function useTestSecret() {
  return useMutation({ mutationFn: (kind: SecretKind) => testSecret(kind) })
}

export function useDeleteSecret() {
  const refresh = useRefreshDependents()
  return useMutation({ mutationFn: (kind: SecretKind) => deleteSecret(kind), onSuccess: refresh })
}

export function useSettings() {
  return useQuery({ queryKey: SETTINGS_QUERY_KEY, queryFn: getSettings })
}

export function useSaveSettings() {
  const queryClient = useQueryClient()
  const refresh = useRefreshDependents()
  return useMutation({
    mutationFn: (changes: Partial<Record<SettingKey, string>>) => saveSettings(changes),
    onSuccess: (data) => {
      queryClient.setQueryData(SETTINGS_QUERY_KEY, data)
      refresh()
    },
  })
}
