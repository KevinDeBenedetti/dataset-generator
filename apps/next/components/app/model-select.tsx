'use client'

import { useTranslations } from 'next-intl'
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
  // Defaults to the translated "Model".
  ariaLabel?: string
  className?: string
}

// max-w-full: a long model name never pushes the select past a narrow screen;
// the open list still shows each name in full.
const DEFAULT_CLASS =
  'h-9 max-w-full rounded-md border bg-transparent px-3 text-sm outline-none focus-visible:border-ring'

// Models grouped by provider; an unconfigured provider's models are listed but
// disabled, so it's clear the option exists and what enabling it takes.
export function ModelSelect({
  value,
  onChange,
  allowDefault = true,
  disabled,
  id,
  ariaLabel,
  className = DEFAULT_CLASS,
}: ModelSelectProps) {
  const t = useTranslations('models.select')
  const { data, isPending } = useModels()
  const llm = data?.model

  return (
    <select
      id={id}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled || isPending}
      aria-label={ariaLabel ?? t('ariaLabel')}
      className={className}
    >
      {allowDefault && (
        <option value="">{llm ? t('yourLlmNamed', { model: llm }) : t('yourLlm')}</option>
      )}
      {!allowDefault && !value && <option value="">{t('pick')}</option>}
      {(data?.providers ?? []).map((provider) => {
        const models = provider.models
        if (models.length === 0) return null
        return (
          <optgroup
            key={provider.name}
            label={
              provider.configured
                ? provider.label
                : t('notConfigured', { provider: provider.label })
            }
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
