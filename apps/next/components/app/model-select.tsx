'use client'

import { useModels } from '@/hooks/use-models'

interface ModelSelectProps {
  // A "<provider>:<model>" reference, or '' for your LLM.
  value: string
  onChange: (ref: string) => void
  // Offer the empty "your LLM" option (off on the Models page, where the
  // select *is* your LLM).
  allowDefault?: boolean
  disabled?: boolean
  id?: string
  ariaLabel?: string
  className?: string
}

const DEFAULT_CLASS =
  'h-9 rounded-md border bg-transparent px-3 text-sm outline-none focus-visible:border-ring'

// Models grouped by provider; an unconfigured provider's models are listed but
// disabled, so it's clear the option exists and what enabling it takes.
export function ModelSelect({
  value,
  onChange,
  allowDefault = true,
  disabled,
  id,
  ariaLabel = 'Model',
  className = DEFAULT_CLASS,
}: ModelSelectProps) {
  const { data, isPending } = useModels()
  const llm = data?.model

  return (
    <select
      id={id}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled || isPending}
      aria-label={ariaLabel}
      className={className}
    >
      {allowDefault && <option value="">{llm ? `Your LLM (${llm})` : 'Your LLM'}</option>}
      {!allowDefault && !value && <option value="">Pick a model…</option>}
      {(data?.providers ?? []).map((provider) => {
        const models = provider.models
        if (models.length === 0) return null
        return (
          <optgroup
            key={provider.name}
            label={provider.configured ? provider.label : `${provider.label} (not configured)`}
          >
            {models.map((m) => (
              <option key={m.ref} value={m.ref} disabled={!provider.configured}>
                {m.label}
              </option>
            ))}
          </optgroup>
        )
      })}
    </select>
  )
}
