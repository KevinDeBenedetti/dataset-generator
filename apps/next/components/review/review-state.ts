// What the tabular review lets you do, from the draft alone (kept apart from
// the component so vitest checks it without a DOM).
import type { QualityRuleResult, TabularDraft } from '@/api/sdk'

export interface ApproveState {
  canApprove: boolean
  canReject: boolean
  // Why approving is not possible: the blocking rules' messages, or the status.
  reasons: string[]
}

export function reviewState(draft: TabularDraft | undefined): ApproveState {
  if (!draft) return { canApprove: false, canReject: false, reasons: [] }
  if (draft.status !== 'succeeded') {
    return { canApprove: false, canReject: false, reasons: [`status:${draft.status}`] }
  }
  const blocking: QualityRuleResult[] = draft.blocking ?? []
  const reasons = blocking.map((rule) => rule.message || rule.rule)
  // A public draft whose licence doesn't allow it can't be published.
  if (draft.visibility === 'public' && draft.public_refusal) reasons.push(draft.public_refusal)
  return { canApprove: reasons.length === 0, canReject: true, reasons }
}

// The recipe's steps with a suggested one added (a `mask` from the quality
// report), unless an equal step is already there.
export function withStep(
  steps: Record<string, unknown>[],
  step: Record<string, unknown>,
): Record<string, unknown>[] {
  const same = (a: Record<string, unknown>) => JSON.stringify(a) === JSON.stringify(step)
  return steps.some(same) ? steps : [...steps, step]
}

// "0.1234" → "12.3 %".
export function percent(share: number | null | undefined, locale: string): string {
  if (share === null || share === undefined) return '—'
  return new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 1 }).format(share)
}
