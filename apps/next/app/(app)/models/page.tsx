'use client'

import Link from 'next/link'
import { useState } from 'react'
import { toast } from 'sonner'
import { Icon } from '@/components/app/icon'
import { ModelSelect } from '@/components/app/model-select'
import {
  useEmbeddingModel,
  useModels,
  useTestModel,
  useUpdateDefaultModel,
} from '@/hooks/use-models'
import type { ModelsResponse, ModelTestResponse, ProviderOut } from '@/api/types'

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
        {provider.configured && provider.endpoint && (
          <p className="hint">
            Calls go to <code className="mono">{provider.endpoint}</code>
            {provider.lent
              ? " with the server's key: you saved none of your own. Save yours in Settings to use your own endpoint instead."
              : ' with your own key.'}
          </p>
        )}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {provider.models.length === 0 && <span className="muted">No models configured.</span>}
          {provider.models.map((m) => (
            <span key={m.ref} className="tag mono">
              {m.label}
            </span>
          ))}
        </div>
        {(provider.embedding_models ?? []).length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
            <span className="hint">Embeddings</span>
            {(provider.embedding_models ?? []).map((m) => (
              <span key={m.ref} className="tag mono" title="Embedding model">
                {m.label}
              </span>
            ))}
          </div>
        )}
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

const pct = (value: number) => `${Math.round(value * 100)}%`

/** The checks' embedding model: picked among your endpoint's, measured on the
 * built-in test set, and used with the thresholds the measurement put. */
function EmbeddingModel({ data }: { data: ModelsResponse }) {
  const options = data.providers.flatMap((p) => p.embedding_models ?? []).map((m) => m.ref)
  const current = data.embedding_model ?? ''
  const [picked, setPicked] = useState(current || options[0] || '')
  const choose = useEmbeddingModel()
  const t = data.embedding_thresholds
  const report = data.embedding_calibration

  const measure = () =>
    choose.mutate(picked, {
      onSuccess: (next) => {
        const r = next.embedding_calibration
        toast.success(
          r
            ? `Measured: duplicates from ${pct(r.dedup.threshold)}, grounding below ${pct(r.grounding.threshold)} held out`
            : 'Embedding model saved',
        )
      },
      onError: (e) => toast.error(e instanceof Error ? e.message : String(e)),
    })

  return (
    <div className="field">
      <label htmlFor="embedding-model" className="label">
        Embedding model
      </label>
      {options.length === 0 ? (
        <div className="input mono" aria-readonly="true">
          None
        </div>
      ) : (
        <div style={{ display: 'flex', gap: 8 }}>
          <select
            id="embedding-model"
            className="input"
            value={picked}
            onChange={(e) => setPicked(e.target.value)}
            disabled={choose.isPending}
          >
            {options.map((ref) => (
              <option key={ref} value={ref}>
                {ref.replace(/^openai:/, '')}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="btn btn-outline"
            disabled={!picked || choose.isPending}
            onClick={measure}
            title="Measure its thresholds on the built-in test set, then use it"
          >
            <Icon
              name={choose.isPending ? 'loader' : 'check'}
              className={choose.isPending ? 'animate-spin' : undefined}
            />
            Measure and use
          </button>
        </div>
      )}
      <div className="hint">
        {current ? (
          <>
            {current.replace(/^openai:/, '')}
            {data.embedding_chosen ? ' (yours)' : ' (the server’s)'}: a rephrasing from{' '}
            {pct(t.dedup)} is dropped, an answer below {pct(t.grounding)} of its source is held for
            review, a section below {pct(t.uncovered)} is asked about.{' '}
            {report
              ? `Measured on the built-in test set: they separate rephrasings ${pct(report.dedup.accuracy)}, faithful answers ${pct(report.grounding.accuracy)} and covered sections ${pct(report.uncovered.accuracy)} of the time.`
              : 'Default thresholds: not measured for this model yet.'}
          </>
        ) : (
          'None on your endpoint: the duplicate and grounding checks compare the words, and no collection can be built.'
        )}
      </div>
      {data.embedding_chosen && (
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          style={{ alignSelf: 'flex-start' }}
          disabled={choose.isPending}
          onClick={() => choose.mutate(null)}
        >
          Back to the server’s model
        </button>
      )}
    </div>
  )
}

export default function ModelsPage() {
  const modelsQuery = useModels(true)
  const updateMutation = useUpdateDefaultModel()
  // What the user picked, until it is saved; null shows the saved LLM.
  const [edit, setEdit] = useState<string | null>(null)

  const saved = modelsQuery.data?.model ?? ''
  const draft = edit ?? saved
  const changed = draft !== '' && draft !== saved

  const save = () =>
    updateMutation.mutate(draft, {
      onSuccess: () => {
        setEdit(null)
        toast.success('LLM saved')
      },
      onError: (e) => toast.error(e instanceof Error ? e.message : String(e)),
    })

  return (
    <div>
      <div className="page-head">
        <div>
          <h1 className="page-title">Models</h1>
          <p className="page-sub">
            Your LLM and the embedding model, on an OpenAI-compatible endpoint (OpenAI, or a gateway
            such as LiteLLM). A generation can still pick another model.
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
                <div className="card-title">Your models</div>
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
              <div className="field">
                <label htmlFor="default-llm" className="label">
                  LLM
                </label>
                <ModelSelect
                  id="default-llm"
                  value={draft}
                  onChange={setEdit}
                  allowDefault={false}
                  disabled={updateMutation.isPending}
                  className="input"
                />
                <div className="hint">
                  Every step: cleaning, Q&amp;A, scoring, the jobs, and the transcription of PDF and
                  image pages — so it must read images.
                </div>
              </div>
              <EmbeddingModel data={modelsQuery.data} />
            </div>
            <div className="card-foot" style={{ gap: 10 }}>
              <button
                className="btn btn-primary"
                type="button"
                disabled={!changed || updateMutation.isPending}
                onClick={save}
              >
                <Icon
                  name={updateMutation.isPending ? 'loader' : 'check'}
                  className={updateMutation.isPending ? 'animate-spin' : undefined}
                />
                Save
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
