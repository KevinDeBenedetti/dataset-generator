'use client'

import { useTranslations } from 'next-intl'
import { type ReactNode, useState } from 'react'
import { toast } from 'sonner'
import { Icon } from '@/components/app/icon'
import { ModelSelect } from '@/components/app/model-select'
import {
  useEmbeddingModel,
  useModels,
  useTestModel,
  useUpdateDefaultModel,
} from '@/hooks/use-models'
import { richLink } from '@/lib/rich'
import type { ModelsResponse, ModelTestResponse, ProviderOut } from '@/api/types'

// The `<code>` tag of the rich messages: a monospace reference or endpoint.
const codeMono = (chunks: ReactNode) => <code className="mono">{chunks}</code>

function ProviderCard({ provider }: { provider: ProviderOut }) {
  const t = useTranslations('models')
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
            {t.rich('provider.references', { name: provider.name, code: codeMono })}
          </div>
        </div>
        <span className={`badge badge-${provider.configured ? 'success' : 'destructive'}`}>
          <span className="dot" />
          {provider.configured ? t('provider.configured') : t('provider.notConfigured')}
        </span>
      </div>
      <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {(provider.missing ?? []).length > 0 && (
          <p className="hint" style={{ color: 'var(--destructive)' }}>
            {t.rich('provider.missing', {
              missing: (provider.missing ?? []).join(', '),
              link: richLink('/settings'),
            })}
          </p>
        )}
        {provider.configured && provider.endpoint && (
          <p className="hint">
            {t.rich(provider.lent ? 'provider.endpointLent' : 'provider.endpointOwn', {
              endpoint: provider.endpoint,
              code: codeMono,
            })}
          </p>
        )}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {provider.models.length === 0 && <span className="muted">{t('provider.noModels')}</span>}
          {provider.models.map((m) => (
            <span key={m.ref} className="tag mono">
              {m.label}
            </span>
          ))}
        </div>
        {(provider.embedding_models ?? []).length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
            <span className="hint">{t('provider.embeddings')}</span>
            {(provider.embedding_models ?? []).map((m) => (
              <span key={m.ref} className="tag mono" title={t('provider.embeddingTitle')}>
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
            aria-label={t('provider.testLabel', { provider: provider.label })}
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
            {t('provider.test')}
          </button>
        </div>
        {result && (
          <p className="hint" style={result.ok ? undefined : { color: 'var(--destructive)' }}>
            {result.ok ? t('provider.testReply', { text: String(result.text) }) : result.error}
            {' · '}
            {result.latency_ms} ms
            {result.usage?.total_cost_usd != null &&
              ` · $${Number(result.usage.total_cost_usd).toFixed(4)}`}
          </p>
        )}
      </div>
    </div>
  )
}

// A 0–1 score as a whole percentage; the messages carry the `%` sign.
const pct = (value: number) => Math.round(value * 100)

/** The checks' embedding model: picked among your endpoint's, measured on the
 * built-in test set, and used with the thresholds the measurement put. */
function EmbeddingModel({ data }: { data: ModelsResponse }) {
  const t = useTranslations('models')
  const tc = useTranslations('common')
  const options = data.providers.flatMap((p) => p.embedding_models ?? []).map((m) => m.ref)
  const current = data.embedding_model ?? ''
  const [picked, setPicked] = useState(current || options[0] || '')
  const choose = useEmbeddingModel()
  const thresholds = data.embedding_thresholds
  const report = data.embedding_calibration

  const measure = () =>
    choose.mutate(picked, {
      onSuccess: (next) => {
        const r = next.embedding_calibration
        toast.success(
          r
            ? t('embedding.measuredToast', {
                dedup: pct(r.dedup.threshold),
                grounding: pct(r.grounding.threshold),
              })
            : t('embedding.saved'),
        )
      },
      onError: (e) => toast.error(e instanceof Error ? e.message : String(e)),
    })

  return (
    <div className="field">
      <label htmlFor="embedding-model" className="label">
        {t('embedding.label')}
      </label>
      {options.length === 0 ? (
        <div className="input mono" aria-readonly="true">
          {tc('none')}
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
            title={t('embedding.measureTitle')}
          >
            <Icon
              name={choose.isPending ? 'loader' : 'check'}
              className={choose.isPending ? 'animate-spin' : undefined}
            />
            {t('embedding.measure')}
          </button>
        </div>
      )}
      <div className="hint">
        {current ? (
          <>
            {t(data.embedding_chosen ? 'embedding.thresholdsYours' : 'embedding.thresholdsServer', {
              model: current.replace(/^openai:/, ''),
              dedup: pct(thresholds.dedup),
              grounding: pct(thresholds.grounding),
              uncovered: pct(thresholds.uncovered),
            })}{' '}
            {report
              ? t('embedding.measured', {
                  dedup: pct(report.dedup.accuracy),
                  grounding: pct(report.grounding.accuracy),
                  uncovered: pct(report.uncovered.accuracy),
                })
              : t('embedding.notMeasured')}
          </>
        ) : (
          t('embedding.none')
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
          {t('embedding.backToServer')}
        </button>
      )}
    </div>
  )
}

export default function ModelsPage() {
  const t = useTranslations('models')
  const tc = useTranslations('common')
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
        toast.success(t('defaults.saved'))
      },
      onError: (e) => toast.error(e instanceof Error ? e.message : String(e)),
    })

  return (
    <div>
      <div className="page-head">
        <div>
          <h1 className="page-title">{t('title')}</h1>
          <p className="page-sub">{t('subtitle')}</p>
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
            {tc('refresh')}
          </button>
        </div>
      </div>

      {modelsQuery.error && (
        <p className="hint" style={{ color: 'var(--destructive)', marginBottom: 18 }}>
          {modelsQuery.error instanceof Error ? modelsQuery.error.message : t('loadFailed')}
        </p>
      )}
      {modelsQuery.isPending && <p className="muted">{t('loading')}</p>}

      {modelsQuery.data && (
        <>
          <div className="card" style={{ marginBottom: 24 }}>
            <div className="card-head">
              <div>
                <div className="card-title">{t('defaults.title')}</div>
                <div className="card-desc">{t('defaults.description')}</div>
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
                  {t('defaults.llm')}
                </label>
                <ModelSelect
                  id="default-llm"
                  value={draft}
                  onChange={setEdit}
                  allowDefault={false}
                  disabled={updateMutation.isPending}
                  className="input"
                />
                <div className="hint">{t('defaults.llmHint')}</div>
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
                {tc('save')}
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
