import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getQualityRules, updateQualityRules, type QualityRulesUpdate } from '@/api/sdk'

export const QUALITY_RULES_QUERY_KEY = ['quality-rules']

export function useQualityRules() {
  return useQuery({
    queryKey: QUALITY_RULES_QUERY_KEY,
    queryFn: getQualityRules,
  })
}

export function useUpdateQualityRules() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (body: QualityRulesUpdate) => updateQualityRules(body),
    onSuccess: (rules) => {
      queryClient.setQueryData(QUALITY_RULES_QUERY_KEY, rules)
    },
  })
}
