'use client'

import { useModels } from '@/hooks/use-models'

interface ModelSelectProps {
  // A "<provider>:<model>" reference, or '' for the role default.
  value: string
  onChange: (ref: string) => void
  // The role whose default the empty option stands for (cleaning, qa, vision, jobs).
  modelRole?: string
  // Offer the empty "role default" option (off on the Models page, where the
  // select *is* the default).
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
  modelRole,
  allowDefault = true,
  disabled,
  id,
  ariaLabel = 'Model',
  className = DEFAULT_CLASS,
}: ModelSelectProps) {
  const { data, isPending } = useModels()
  const roleDefault = modelRole ? data?.defaults[modelRole] : undefined

  return (
    <select
      id={id}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled || isPending}
      aria-label={ariaLabel}
      className={className}
    >
      {allowDefault && (
        <option value="">{roleDefault ? `Default (${roleDefault})` : 'Server default'}</option>
      )}
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
