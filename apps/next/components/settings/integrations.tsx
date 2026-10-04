'use client'

import { useState } from 'react'
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

interface SecretDef {
  kind: SecretKind
  label: string
  placeholder: string
  help: string
}

interface SettingDef {
  key: SettingKey
  label: string
  placeholder: string
  help?: string
}

interface Group {
  title: string
  description: string
  secrets: SecretDef[]
  settings: SettingDef[]
}

const GROUPS: Group[] = [
  {
    title: 'OpenAI',
    description:
      'Your own API key pays for cleaning, Q&A generation, vision and embeddings run with an OpenAI model.',
    secrets: [
      {
        kind: 'openai_api_key',
        label: 'API key',
        placeholder: 'sk-…',
        help: 'Create one at platform.openai.com/api-keys.',
      },
    ],
    settings: [
      {
        key: 'openai_base_url',
        label: 'Base URL (optional)',
        placeholder: 'https://api.openai.com/v1',
        help: 'Only for an OpenAI-compatible endpoint your administrator allows. Leave empty for OpenAI.',
      },
    ],
  },
  {
    title: 'Claude',
    description:
      'Use your Claude subscription (or an Anthropic API key) for any model step. Not available when the administrator has disabled it.',
    secrets: [
      {
        kind: 'claude_token',
        label: 'Subscription token',
        placeholder: 'sk-ant-oat01-…',
        help: 'Run `claude setup-token` in a terminal and paste the result.',
      },
      {
        kind: 'anthropic_api_key',
        label: 'Anthropic API key (instead)',
        placeholder: 'sk-ant-api03-…',
        help: 'Billed per token. Used only when there is no subscription token.',
      },
    ],
    settings: [],
  },
  {
    title: 'Hugging Face',
    description: 'Where your jobs and dataset exports publish (always as private repos).',
    secrets: [
      {
        kind: 'hf_token',
        label: 'Access token',
        placeholder: 'hf_…',
        help: 'A token with write access, from huggingface.co/settings/tokens.',
      },
    ],
    settings: [
      {
        key: 'hf_namespace',
        label: 'Namespace (optional)',
        placeholder: 'your-user-or-org',
        help: 'Defaults to the account the token belongs to.',
      },
      {
        key: 'hf_qa_repo',
        label: 'Q&A dataset repo',
        placeholder: 'github-qa',
        help: 'Where the GitHub personal Q&A job publishes.',
      },
      {
        key: 'hf_corpus_repo',
        label: 'Corpus dataset repo',
        placeholder: 'github-corpus',
        help: 'Where the knowledge corpus job publishes.',
      },
    ],
  },
  {
    title: 'GitHub',
    description: 'Public repositories are read to build your datasets.',
    secrets: [
      {
        kind: 'github_token',
        label: 'Personal access token (optional)',
        placeholder: 'github_pat_…',
        help: 'Without one GitHub allows 60 requests an hour — too few for a code export.',
      },
    ],
    settings: [
      {
        key: 'github_username',
        label: 'Username',
        placeholder: 'octocat',
        help: 'Whose public repositories the jobs read.',
      },
    ],
  },
]

function SecretRow({ def, status }: { def: SecretDef; status?: SecretStatus }) {
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
          toast.success(check.ok ? `${def.label} saved — ${check.message}` : `${def.label} saved`)
        },
        onError: (error: Error) => setRefused(error.message),
      },
    )
  }

  return (
    <div className="field">
      <label htmlFor={`secret-${def.kind}`} className="label">
        {def.label}{' '}
        <span className={`badge badge-${configured ? 'success' : 'secondary'}`}>
          <span className="dot" />
          {configured ? (status?.hint ? `Saved · …${status.hint}` : 'Saved') : 'Not set'}
        </span>
      </label>
      <div style={{ display: 'flex', gap: 8 }}>
        <input
          id={`secret-${def.kind}`}
          className="input mono"
          type="password"
          autoComplete="off"
          spellCheck={false}
          placeholder={configured ? 'Paste a new value to replace it' : def.placeholder}
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
          Save
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
              Test
            </button>
            <button
              className="btn btn-outline"
              type="button"
              disabled={busy}
              onClick={() =>
                remove.mutate(def.kind, {
                  onSuccess: () => toast.success(`${def.label} removed`),
                  onError: (e: Error) => toast.error(e.message),
                })
              }
            >
              <Icon name="trash" />
              Remove
            </button>
          </>
        )}
      </div>
      <p className="hint">{def.help} It is stored encrypted and never shown again.</p>
      {refused && (
        <p className="hint" style={{ color: 'var(--destructive)' }}>
          {refused}{' '}
          <button className="btn btn-outline btn-sm" type="button" onClick={() => submit(true)}>
            Save anyway
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
            {def.label}
          </label>
          <input
            id={`setting-${def.key}`}
            className="input"
            placeholder={def.placeholder}
            value={current(def.key)}
            onChange={(e) => setDraft({ ...draft, [def.key]: e.target.value })}
          />
          {def.help && <p className="hint">{def.help}</p>}
        </div>
      ))}
      <div>
        <button
          className="btn btn-outline"
          type="button"
          disabled={!dirty || save.isPending}
          onClick={() =>
            save.mutate(draft, {
              onSuccess: () => toast.success('Settings saved'),
              onError: (e: Error) => toast.error(e.message),
            })
          }
        >
          <Icon
            name={save.isPending ? 'loader' : 'check'}
            className={save.isPending ? 'animate-spin' : undefined}
          />
          Save settings
        </button>
      </div>
    </>
  )
}

export function Integrations() {
  const secrets = useSecrets()
  const byKind = new Map((secrets.data ?? []).map((s) => [s.kind, s]))

  return (
    <>
      {GROUPS.map((group) => (
        <div className="card" key={group.title}>
          <div className="card-head">
            <div>
              <div className="card-title">{group.title}</div>
              <div className="card-desc">{group.description}</div>
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
