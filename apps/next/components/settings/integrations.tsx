'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'
import { Icon } from '@/components/app/icon'
import {
  useDeleteSecret,
  useSaveSecret,
  useSaveSettings,
  useSecrets,
  useSettings,
  useTestSecret,
} from '@/hooks/use-integrations'
import type { SecretKind, SecretStatus, SettingKey } from '@/api/sdk'

// Labels, help texts and group titles are message keys of the `settings`
// namespace: `integrations.secrets.<kind>`, `integrations.settings.<key>` and
// `integrations.groups.<id>`.
interface SecretDef {
  kind: SecretKind
  placeholder: string
}

interface SettingDef {
  key: SettingKey
  /** A literal sample value; when missing, the placeholder is a message. */
  placeholder?: string
}

interface Group {
  id: 'endpoint' | 'huggingFace' | 'github'
  secrets: SecretDef[]
  settings: SettingDef[]
}

const GROUPS: Group[] = [
  {
    id: 'endpoint',
    secrets: [{ kind: 'openai_api_key', placeholder: 'sk-…' }],
    settings: [{ key: 'openai_base_url', placeholder: 'https://api.openai.com/v1' }],
  },
  {
    id: 'huggingFace',
    secrets: [{ kind: 'hf_token', placeholder: 'hf_…' }],
    settings: [
      { key: 'hf_namespace' },
      { key: 'hf_qa_repo', placeholder: 'github-qa' },
      { key: 'hf_corpus_repo', placeholder: 'github-corpus' },
    ],
  },
  {
    id: 'github',
    secrets: [{ kind: 'github_token', placeholder: 'github_pat_…' }],
    settings: [{ key: 'github_username', placeholder: 'octocat' }],
  },
]

function SecretRow({ def, status }: { def: SecretDef; status?: SecretStatus }) {
  const t = useTranslations('settings')
  const tc = useTranslations('common')
  const label = t(`integrations.secrets.${def.kind}.label`)
  const [value, setValue] = useState('')
  const [refused, setRefused] = useState<string | null>(null)
  const save = useSaveSecret()
  const test = useTestSecret()
  const remove = useDeleteSecret()
  const configured = status?.configured === true
  const busy = save.isPending || remove.isPending

  const submit = (force = false) => {
    setRefused(null)
    save.mutate(
      { kind: def.kind, value: value.trim(), force },
      {
        onSuccess: ({ check }) => {
          setValue('')
          toast.success(
            check.ok
              ? t('integrations.secretSavedChecked', { label, message: check.message })
              : t('integrations.secretSaved', { label }),
          )
        },
        onError: (error: Error) => setRefused(error.message),
      },
    )
  }

  return (
    <div className="field">
      <label htmlFor={`secret-${def.kind}`} className="label">
        {label}{' '}
        <span className={`badge badge-${configured ? 'success' : 'secondary'}`}>
          <span className="dot" />
          {configured
            ? status?.hint
              ? t('integrations.statusSavedHint', { hint: status.hint })
              : t('integrations.statusSaved')
            : t('integrations.statusNotSet')}
        </span>
      </label>
      <div style={{ display: 'flex', gap: 8 }}>
        <input
          id={`secret-${def.kind}`}
          className="input mono"
          type="password"
          autoComplete="off"
          spellCheck={false}
          placeholder={configured ? t('integrations.replacePlaceholder') : def.placeholder}
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
        <button
          className="btn btn-primary"
          type="button"
          disabled={!value.trim() || busy}
          onClick={() => submit()}
        >
          <Icon
            name={save.isPending ? 'loader' : 'check'}
            className={save.isPending ? 'animate-spin' : undefined}
          />
          {tc('save')}
        </button>
        {configured && (
          <>
            <button
              className="btn btn-outline"
              type="button"
              disabled={test.isPending}
              onClick={() =>
                test.mutate(def.kind, {
                  onSuccess: (r) => (r.ok ? toast.success(r.message) : toast.error(r.message)),
                  onError: (e: Error) => toast.error(e.message),
                })
              }
            >
              <Icon
                name={test.isPending ? 'loader' : 'play'}
                className={test.isPending ? 'animate-spin' : undefined}
              />
              {t('integrations.test')}
            </button>
            <button
              className="btn btn-outline"
              type="button"
              disabled={busy}
              onClick={() =>
                remove.mutate(def.kind, {
                  onSuccess: () => toast.success(t('integrations.secretRemoved', { label })),
                  onError: (e: Error) => toast.error(e.message),
                })
              }
            >
              <Icon name="trash" />
              {t('integrations.remove')}
            </button>
          </>
        )}
      </div>
      <p className="hint">
        {t(`integrations.secrets.${def.kind}.help`)} {t('integrations.storedEncrypted')}
      </p>
      {refused && (
        <p className="hint" style={{ color: 'var(--destructive)' }}>
          {refused}{' '}
          <button className="btn btn-outline btn-sm" type="button" onClick={() => submit(true)}>
            {t('integrations.saveAnyway')}
          </button>
        </p>
      )}
    </div>
  )
}

function SettingsFields({ defs }: { defs: SettingDef[] }) {
  const { data } = useSettings()
  if (defs.length === 0) return null
  // Keyed by the saved values: a save (or a reload) remounts the form with an
  // empty draft, instead of resetting it from an effect.
  return <SettingsForm key={JSON.stringify(data ?? {})} defs={defs} data={data} />
}

function SettingsForm({
  defs,
  data,
}: {
  defs: SettingDef[]
  data: Partial<Record<SettingKey, string>> | undefined
}) {
  const t = useTranslations('settings')
  const save = useSaveSettings()
  const [draft, setDraft] = useState<Partial<Record<SettingKey, string>>>({})

  const current = (key: SettingKey) => draft[key] ?? data?.[key] ?? ''
  const dirty = defs.some(
    (d) => draft[d.key] !== undefined && draft[d.key] !== (data?.[d.key] ?? ''),
  )

  return (
    <>
      {defs.map((def) => (
        <div className="field" key={def.key}>
          <label htmlFor={`setting-${def.key}`} className="label">
            {t(`integrations.settings.${def.key}.label`)}
          </label>
          <input
            id={`setting-${def.key}`}
            className="input"
            placeholder={
              def.placeholder ??
              (def.key === 'hf_namespace'
                ? t('integrations.settings.hf_namespace.placeholder')
                : undefined)
            }
            value={current(def.key)}
            onChange={(e) => setDraft({ ...draft, [def.key]: e.target.value })}
          />
          <p className="hint">{t(`integrations.settings.${def.key}.help`)}</p>
        </div>
      ))}
      <div>
        <button
          className="btn btn-outline"
          type="button"
          disabled={!dirty || save.isPending}
          onClick={() =>
            save.mutate(draft, {
              onSuccess: () => toast.success(t('integrations.settingsSaved')),
              onError: (e: Error) => toast.error(e.message),
            })
          }
        >
          <Icon
            name={save.isPending ? 'loader' : 'check'}
            className={save.isPending ? 'animate-spin' : undefined}
          />
          {t('integrations.saveSettings')}
        </button>
      </div>
    </>
  )
}

export function Integrations() {
  const t = useTranslations('settings')
  const secrets = useSecrets()
  const byKind = new Map((secrets.data ?? []).map((s) => [s.kind, s]))

  return (
    <>
      {GROUPS.map((group) => (
        <div className="card" key={group.id}>
          <div className="card-head">
            <div>
              <div className="card-title">{t(`integrations.groups.${group.id}.title`)}</div>
              <div className="card-desc">{t(`integrations.groups.${group.id}.description`)}</div>
            </div>
          </div>
          <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {group.secrets.map((def) => (
              <SecretRow key={def.kind} def={def} status={byKind.get(def.kind)} />
            ))}
            <SettingsFields defs={group.settings} />
          </div>
        </div>
      ))}
    </>
  )
}
