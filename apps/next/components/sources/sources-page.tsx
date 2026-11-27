'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useLocale, useTranslations } from 'next-intl'
import { toast } from 'sonner'
import type { DataSource } from '@/api/sdk'
import { Icon } from '@/components/app/icon'
import { repoSlug } from '@/components/recipes/recipe-state'
import { DatagouvSearch } from './datagouv-search'
import { RestForm } from './rest-form'
import { SqlRemoteForm } from './sql-remote-form'
import { UrlForm } from './url-form'
import {
  useConnectors,
  useCreateRecipe,
  useDataSources,
  useDeleteDataSource,
  useUpdateDataSource,
  useUploadDataSource,
} from '@/hooks/use-data-sources'

const FORMATS = ['', 'csv', 'tsv', 'json', 'jsonl', 'parquet', 'xlsx'] as const

function UploadForm({ onDone }: { onDone: () => void }) {
  const t = useTranslations('sources')
  const upload = useUploadDataSource()
  const [file, setFile] = useState<File | null>(null)
  const [name, setName] = useState('')
  const [licence, setLicence] = useState('')
  const [format, setFormat] = useState('')
  const [delimiter, setDelimiter] = useState('')
  const [encoding, setEncoding] = useState('')
  const [sheet, setSheet] = useState('')
  const [progress, setProgress] = useState<number | null>(null)

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!file) return
    setProgress(0)
    upload.mutate(
      {
        params: {
          file,
          name: name.trim() || file.name,
          licence,
          format,
          delimiter,
          encoding,
          sheet,
        },
        onProgress: (done, total) => setProgress(Math.round((done / total) * 100)),
      },
      {
        onSuccess: () => {
          toast.success(t('uploaded'))
          setProgress(null)
          onDone()
        },
        onError: (err: Error) => {
          setProgress(null)
          toast.error(err.message)
        },
      },
    )
  }

  return (
    <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div className="field">
        <label className="label" htmlFor="source-file">
          {t('file')}
        </label>
        <input
          id="source-file"
          type="file"
          accept=".csv,.tsv,.txt,.json,.jsonl,.ndjson,.parquet,.xlsx,.sql,.gz"
          onChange={(e) => {
            const picked = e.target.files?.[0] ?? null
            setFile(picked)
            if (picked && !name) setName(picked.name.replace(/\.[^.]+$/, ''))
          }}
        />
      </div>
      <div className="field">
        <label className="label" htmlFor="source-name">
          {t('name')}
        </label>
        <input
          id="source-name"
          className="input"
          value={name}
          maxLength={100}
          onChange={(e) => setName(e.target.value)}
        />
      </div>
      <div className="field">
        <label className="label" htmlFor="source-licence">
          {t('licence')}
        </label>
        <input
          id="source-licence"
          className="input"
          value={licence}
          maxLength={200}
          placeholder={t('licencePlaceholder')}
          onChange={(e) => setLicence(e.target.value)}
        />
        <div className="hint">{t('licenceHint')}</div>
      </div>
      <details>
        <summary className="hint">{t('readingOptions')}</summary>
        <div
          style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8, marginTop: 8 }}
        >
          <label className="label">
            {t('format')}
            <select className="input" value={format} onChange={(e) => setFormat(e.target.value)}>
              {FORMATS.map((f) => (
                <option key={f} value={f}>
                  {f || t('detect')}
                </option>
              ))}
            </select>
          </label>
          <label className="label">
            {t('delimiter')}
            <input
              className="input mono"
              value={delimiter}
              maxLength={1}
              placeholder={t('detect')}
              onChange={(e) => setDelimiter(e.target.value)}
            />
          </label>
          <label className="label">
            {t('encoding')}
            <input
              className="input mono"
              value={encoding}
              maxLength={32}
              placeholder={t('detect')}
              onChange={(e) => setEncoding(e.target.value)}
            />
          </label>
          <label className="label">
            {t('sheet')}
            <input
              className="input"
              value={sheet}
              maxLength={100}
              onChange={(e) => setSheet(e.target.value)}
            />
          </label>
        </div>
      </details>
      {progress !== null && (
        <progress max={100} value={progress} aria-label={t('progress')}>
          {progress}%
        </progress>
      )}
      <div>
        <button className="btn btn-primary" type="submit" disabled={!file || upload.isPending}>
          <Icon name="upload" />
          {t('upload')}
        </button>
      </div>
    </form>
  )
}

// A SQL dump's tables, listed when it was uploaded: the one that is the data.
function DumpTablePicker({ source }: { source: DataSource }) {
  const t = useTranslations('sources')
  const save = useUpdateDataSource(source.id)
  const config = source.config as {
    table?: string | null
    tables?: { name: string; rows: number }[]
  }
  return (
    <label className="label">
      {t('dumpTable')}
      <select
        className="input"
        value={config.table ?? ''}
        disabled={save.isPending}
        onChange={(e) =>
          save.mutate(
            { config: { ...source.config, table: e.target.value || null } },
            { onError: (err: Error) => toast.error(err.message) },
          )
        }
      >
        <option value="">{t('dumpPick')}</option>
        {(config.tables ?? []).map((table) => (
          <option key={table.name} value={table.name}>
            {t('dumpTableRows', { name: table.name, rows: table.rows })}
          </option>
        ))}
      </select>
    </label>
  )
}

function SourceRow({ source }: { source: DataSource }) {
  const t = useTranslations('sources')
  const locale = useLocale()
  const router = useRouter()
  const remove = useDeleteDataSource()
  const create = useCreateRecipe()
  const config = source.config as { filename?: string; format?: string; dialect?: string }
  return (
    <tr>
      <td>
        <div style={{ fontWeight: 500 }}>{source.name}</div>
        <div className="hint">
          {source.connector}
          {config.filename ? ` · ${config.filename}` : ''}
          {config.format ? ` · ${config.format}` : ''}
          {config.dialect ? ` · ${config.dialect}` : ''}
        </div>
        {source.connector === 'sql_dump' && <DumpTablePicker source={source} />}
      </td>
      <td>{source.licence || '—'}</td>
      <td>
        {source.last_fetched_at
          ? new Date(source.last_fetched_at).toLocaleString(locale)
          : t('neverFetched')}
      </td>
      <td style={{ display: 'flex', gap: 6 }}>
        <button
          type="button"
          className="btn btn-outline btn-sm"
          disabled={create.isPending}
          onClick={() =>
            create.mutate(
              {
                name: source.name,
                data_source_id: source.id,
                target_repo: repoSlug(source.name),
              },
              {
                onSuccess: (recipe) => router.push(`/recipes/${recipe.id}`),
                onError: (e: Error) => toast.error(e.message),
              },
            )
          }
        >
          <Icon name="plus" />
          {t('newRecipe')}
        </button>
        <button
          type="button"
          className="btn btn-outline btn-sm"
          disabled={remove.isPending}
          onClick={() => {
            if (window.confirm(t('confirmDelete', { name: source.name }))) {
              remove.mutate(source.id, { onError: (e: Error) => toast.error(e.message) })
            }
          }}
        >
          {t('delete')}
        </button>
      </td>
    </tr>
  )
}

// Data sources: what rows come from (ADR 0001). Add one from a connector,
// then make a recipe of it.
export function SourcesPage() {
  const t = useTranslations('sources')
  const { data, isPending, error } = useDataSources()
  const { data: connectors } = useConnectors()
  const [adding, setAdding] = useState(false)
  const [kind, setKind] = useState('upload')
  const sources = data?.data_sources ?? []
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      <div className="page-head">
        <div>
          <h1 className="page-title">{t('title')}</h1>
          <p className="page-sub">{t('subtitle')}</p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <Link className="btn btn-outline" href="/recipes">
            {t('recipes')}
          </Link>
          <button className="btn btn-primary" type="button" onClick={() => setAdding(!adding)}>
            <Icon name="plus" />
            {t('add')}
          </button>
        </div>
      </div>

      {adding && (
        <div className="card">
          <div className="card-head">
            <div>
              <div className="card-title">{t('addTitle')}</div>
              <div className="card-desc">
                {(connectors?.connectors ?? [])
                  .map((c) => `${c.title}: ${c.description}`)
                  .join(' · ')}
              </div>
            </div>
          </div>
          <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div className="tabs" role="tablist" aria-label={t('connector')}>
              {(connectors?.connectors ?? []).map((c) => (
                <button
                  key={c.kind}
                  type="button"
                  role="tab"
                  aria-selected={kind === c.kind}
                  className={kind === c.kind ? 'tab active' : 'tab'}
                  onClick={() => setKind(c.kind)}
                >
                  {c.title}
                </button>
              ))}
            </div>
            {kind === 'datagouv' ? (
              <DatagouvSearch onDone={() => setAdding(false)} />
            ) : kind === 'url' ? (
              <UrlForm onDone={() => setAdding(false)} />
            ) : kind === 'rest' ? (
              <RestForm onDone={() => setAdding(false)} />
            ) : kind === 'sql_remote' ? (
              <SqlRemoteForm onDone={() => setAdding(false)} />
            ) : (
              <UploadForm onDone={() => setAdding(false)} />
            )}
          </div>
        </div>
      )}

      <div className="card">
        <div className="card-body">
          {isPending && <p className="hint">{t('loading')}</p>}
          {error && <p className="hint">{error.message}</p>}
          {!isPending && sources.length === 0 && <p className="hint">{t('empty')}</p>}
          {sources.length > 0 && (
            <table className="table">
              <thead>
                <tr>
                  <th>{t('name')}</th>
                  <th>{t('licence')}</th>
                  <th>{t('lastFetch')}</th>
                  <th>{t('actions')}</th>
                </tr>
              </thead>
              <tbody>
                {sources.map((source) => (
                  <SourceRow key={source.id} source={source} />
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}
