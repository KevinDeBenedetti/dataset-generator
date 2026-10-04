'use client'

import Link from 'next/link'
import { useState } from 'react'
import { toast } from 'sonner'
import { Icon } from '@/components/app/icon'
import { ModelSelect } from '@/components/app/model-select'
import { useModels, useTestModel, useUpdateModelDefaults } from '@/hooks/use-models'
import type { ModelTestResponse, ProviderOut } from '@/api/types'

const ROLE_INFO: Record<string, { label: string; hint: string }> = {
  cleaning: { label: 'Cleaning', hint: 'Tidies web page text before Q&A generation' },
  qa: { label: 'Q&A generation', hint: 'Writes the question/answer pairs, and judges scores' },
  vision: { label: 'Vision', hint: 'Transcribes uploaded PDF and image pages' },
  jobs: { label: 'Jobs', hint: 'Dataset jobs run from the Jobs page' },
}

function ProviderCard({ provider }: { provider: ProviderOut }) {
  const [selected, setSelected] = useState(provider.models[0]?.ref ?? '')
  const [result, setResult] = useState<ModelTestResponse | null>(null)
  const testMutation = useTestModel()

  const runTest = () =>
    testMutation.mutate(selected, {
      onSuccess: setResult,
      onError: (e) => toast.error(e instanceof Error ? e.message : String(e)),
    })

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <div className="card-title">{provider.label}</div>
          <div className="card-desc">
            References start with <code className="mono">{provider.name}:</code>
          </div>
        </div>
        <span className={`badge badge-${provider.configured ? 'success' : 'destructive'}`}>
          <span className="dot" />
          {provider.configured ? 'Configured' : 'Not configured'}
        </span>
      </div>
      <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {(provider.missing ?? []).length > 0 && (
          <p className="hint" style={{ color: 'var(--destructive)' }}>
            Add {(provider.missing ?? []).join(', ')} in <Link href="/settings">Settings</Link> to
            enable it.
          </p>
        )}
        {provider.name === 'claude' && (
          <p className="hint">
            Calls go through the Claude Agent SDK with{' '}
            <code className="mono">claude setup-token</code> and bill against your Claude
            subscription.
          </p>
        )}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {provider.models.length === 0 && <span className="muted">No models configured.</span>}
          {provider.models.map((m) => (
            <span key={m.ref} className="tag mono" title={m.vision ? 'Vision-capable' : undefined}>
              {m.label}
              {m.vision ? ' · vision' : ''}
            </span>
          ))}
        </div>
      </div>
      <div
        className="card-foot"
        style={{ flexDirection: 'column', alignItems: 'stretch', gap: 10 }}
      >
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <select
            className="input"
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
            aria-label={`${provider.label} model to test`}
            disabled={!provider.configured || testMutation.isPending}
          >
            {provider.models.map((m) => (
              <option key={m.ref} value={m.ref}>
                {m.label}
              </option>
            ))}
          </select>
          <button
            className="btn btn-outline"
            type="button"
            disabled={!provider.configured || !selected || testMutation.isPending}
            onClick={runTest}
          >
            <Icon
              name={testMutation.isPending ? 'loader' : 'play'}
              className={testMutation.isPending ? 'animate-spin' : undefined}
            />
            Test
          </button>
        </div>
        {result && (
          <p className="hint" style={result.ok ? undefined : { color: 'var(--destructive)' }}>
            {result.ok ? `“${result.text}”` : result.error} · {result.latency_ms} ms
            {result.usage?.total_cost_usd != null &&
              ` · $${Number(result.usage.total_cost_usd).toFixed(4)}`}
          </p>
        )}
      </div>
    </div>
  )
}

export default function ModelsPage() {
  const modelsQuery = useModels(true)
  const updateMutation = useUpdateModelDefaults()
  // Only what the user has edited; everything else shows the saved defaults.
  const [edits, setEdits] = useState<Record<string, string>>({})

  const defaults = modelsQuery.data?.defaults
  const draft: Record<string, string> = { ...defaults, ...edits }

  const changed = Object.entries(draft).filter(([role, ref]) => ref && defaults?.[role] !== ref)

  const save = () =>
    updateMutation.mutate(Object.fromEntries(changed), {
      onSuccess: () => toast.success('Model defaults saved'),
      onError: (e) => toast.error(e instanceof Error ? e.message : String(e)),
    })

  return (
    <div>
      <div className="page-head">
        <div>
          <h1 className="page-title">Models</h1>
          <p className="page-sub">
            Model providers and the default model of each step. Any step can run on the OpenAI API
            or on your Claude subscription; a generation can still pick another model.
          </p>
        </div>
        <div className="page-actions">
          <button
            className="btn btn-outline"
            onClick={() => modelsQuery.refetch()}
            disabled={modelsQuery.isRefetching}
            type="button"
          >
            <Icon
              name="refresh"
              className={modelsQuery.isRefetching ? 'animate-spin' : undefined}
            />
            Refresh
          </button>
        </div>
      </div>

      {modelsQuery.error && (
        <p className="hint" style={{ color: 'var(--destructive)', marginBottom: 18 }}>
          {modelsQuery.error instanceof Error ? modelsQuery.error.message : 'Failed to load models'}
        </p>
      )}
      {modelsQuery.isPending && <p className="muted">Loading models…</p>}

      {modelsQuery.data && (
        <>
          <div className="card" style={{ marginBottom: 24 }}>
            <div className="card-head">
              <div>
                <div className="card-title">Defaults</div>
                <div className="card-desc">Used whenever a request doesn&apos;t name a model.</div>
              </div>
            </div>
            <div
              className="card-body"
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
                gap: 16,
              }}
            >
              {modelsQuery.data.roles.map((role) => (
                <div className="field" key={role}>
                  <label htmlFor={`role-${role}`} className="label">
                    {ROLE_INFO[role]?.label ?? role}
                  </label>
                  <ModelSelect
                    id={`role-${role}`}
                    value={draft[role] ?? ''}
                    onChange={(ref) => setEdits((e) => ({ ...e, [role]: ref }))}
                    allowDefault={false}
                    disabled={updateMutation.isPending}
                    className="input"
                  />
                  <div className="hint">{ROLE_INFO[role]?.hint}</div>
                </div>
              ))}
            </div>
            <div className="card-foot" style={{ gap: 10 }}>
              <button
                className="btn btn-primary"
                type="button"
                disabled={changed.length === 0 || updateMutation.isPending}
                onClick={save}
              >
                <Icon
                  name={updateMutation.isPending ? 'loader' : 'check'}
                  className={updateMutation.isPending ? 'animate-spin' : undefined}
                />
                Save defaults
              </button>
            </div>
          </div>

          <div className="grid-2" style={{ alignItems: 'start', gap: 24 }}>
            {modelsQuery.data.providers.map((provider) => (
              <ProviderCard key={provider.name} provider={provider} />
            ))}
          </div>
        </>
      )}
    </div>
  )
}
