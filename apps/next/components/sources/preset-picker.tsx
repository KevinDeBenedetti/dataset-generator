'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'
import { listRestPresets, restPresetConfig, type PresetField, type RestPreset } from '@/api/sdk'

export interface PickedPreset {
  name: string
  licence: string
  config: Record<string, unknown>
  needsKey: boolean
  keyUrl: string | null
}

// A field's kind, from its JSON Schema (an optional one is anyOf [x, null]).
function fieldKind(field: PresetField): { type: string; options: string[] } {
  const own = field.anyOf?.find((f) => f.type !== 'null') ?? field
  return { type: own.type ?? 'string', options: own.enum ?? [] }
}

// French public APIs ready-made (#320): pick one, fill its few fields, and
// the REST form below receives its config, name and licence.
export function PresetPicker({ onPick }: { onPick: (picked: PickedPreset) => void }) {
  const t = useTranslations('sources.rest')
  const { data } = useQuery({ queryKey: ['rest-presets'], queryFn: listRestPresets })
  const [presetId, setPresetId] = useState('')
  const [values, setValues] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const preset: RestPreset | undefined = data?.presets.find((p) => p.id === presetId)
  const fields = Object.entries(preset?.form_schema.properties ?? {})

  const apply = async () => {
    if (!preset) return
    const params: Record<string, unknown> = {}
    for (const [name, field] of fields) {
      const raw = values[name]
      if (raw === undefined || raw === '') continue
      const { type } = fieldKind(field)
      params[name] = type === 'number' || type === 'integer' ? Number(raw) : raw
    }
    setBusy(true)
    try {
      const made = await restPresetConfig(preset.id, params)
      onPick({
        name: made.name,
        licence: made.licence,
        config: made.config,
        needsKey: made.needs_key,
        keyUrl: preset.key_url,
      })
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card">
      <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <label className="label">
          {t('preset')}
          <select
            className="input"
            value={presetId}
            onChange={(e) => {
              setPresetId(e.target.value)
              setValues({})
            }}
          >
            <option value="">{t('presetNone')}</option>
            {(data?.presets ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                {p.title}
              </option>
            ))}
          </select>
        </label>
        {preset && (
          <>
            <p className="hint">
              {preset.description} —{' '}
              {t('presetFacts', {
                licence: preset.licence,
                producer: preset.producer,
                rate: preset.rate_limit_per_s,
              })}{' '}
              <a className="underline" href={preset.docs_url} target="_blank" rel="noreferrer">
                {t('presetDocs')}
              </a>
            </p>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}>
              {fields.map(([name, field]) => {
                const { type, options } = fieldKind(field)
                const value = values[name] ?? (field.default != null ? String(field.default) : '')
                const set = (v: string) => setValues({ ...values, [name]: v })
                return (
                  <label key={name} className="label">
                    {field.title ?? name}
                    {options.length > 0 ? (
                      <select className="input" value={value} onChange={(e) => set(e.target.value)}>
                        {!preset.form_schema.required?.includes(name) && (
                          <option value="">—</option>
                        )}
                        {options.map((o) => (
                          <option key={o} value={o}>
                            {o}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <input
                        className="input"
                        type={type === 'number' || type === 'integer' ? 'number' : 'text'}
                        step={type === 'number' ? 'any' : undefined}
                        value={value}
                        placeholder={field.description}
                        onChange={(e) => set(e.target.value)}
                      />
                    )}
                  </label>
                )
              })}
            </div>
            {preset.needs_key && <p className="hint">{t('presetKey')}</p>}
            {preset.steps.length > 0 && <p className="hint">{t('presetSteps')}</p>}
            <div>
              <button
                type="button"
                className="btn btn-outline btn-sm"
                disabled={busy}
                onClick={() => void apply()}
              >
                {t('presetApply')}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
