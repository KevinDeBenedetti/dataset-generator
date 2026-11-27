'use client'

import { useEffect, useState } from 'react'
import { useLocale, useTranslations } from 'next-intl'
import { toast } from 'sonner'
import type { ConnectorCandidate, DatagouvResource } from '@/api/sdk'
import { useCreateDataSource, useDatagouvProfile, useDiscover } from '@/hooks/use-data-sources'

const SEARCH_DELAY_MS = 400

function size(bytes: number | null, locale: string): string {
  if (!bytes) return ''
  return new Intl.NumberFormat(locale, {
    style: 'unit',
    unit: bytes > 1024 ** 2 ? 'megabyte' : 'kilobyte',
    maximumFractionDigits: 1,
  }).format(bytes > 1024 ** 2 ? bytes / 1024 ** 2 : bytes / 1024)
}

function Profile({ resourceId }: { resourceId: string }) {
  const t = useTranslations('sources.datagouv')
  const { data, isPending, error } = useDatagouvProfile(resourceId)
  if (isPending) return <p className="hint">{t('profileLoading')}</p>
  if (error) return <p className="hint">{t('noProfile')}</p>
  const header = (data?.header as string[]) ?? []
  const columns = (data?.columns as Record<string, { format?: string }>) ?? {}
  return (
    <div className="hint">
      {t('profile', {
        lines: Number(data?.total_lines ?? 0),
        encoding: String(data?.encoding ?? '—'),
        separator: String(data?.separator ?? '—'),
      })}
      <ul>
        {header.map((name) => (
          <li key={name}>
            <span className="mono">{name}</span> · {columns[name]?.format ?? '—'}
          </li>
        ))}
      </ul>
    </div>
  )
}

function Result({ candidate, onDone }: { candidate: ConnectorCandidate; onDone: () => void }) {
  const t = useTranslations('sources.datagouv')
  const locale = useLocale()
  const create = useCreateDataSource()
  const extra = candidate.extra as {
    dataset_id: string
    organization?: string
    licence?: string
    page?: string
    resources: DatagouvResource[]
  }
  const [picked, setPicked] = useState<DatagouvResource | null>(null)
  const [mode, setMode] = useState<'file' | 'tabular_api'>('file')
  const [name, setName] = useState(candidate.title)
  return (
    <div className="card">
      <div className="card-head">
        <div>
          <div className="card-title">{candidate.title}</div>
          <div className="card-desc">
            {extra.organization ?? '—'} ·{' '}
            <span className="badge badge-info">{extra.licence ?? t('noLicence')}</span>
            {extra.page && (
              <>
                {' '}
                ·{' '}
                <a
                  className="underline"
                  href={extra.page}
                  target="_blank"
                  rel="noreferrer noopener"
                >
                  data.gouv.fr
                </a>
              </>
            )}
          </div>
        </div>
      </div>
      <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <ul>
          {extra.resources.map((r) => (
            <li key={r.id}>
              <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <input
                  type="radio"
                  name={`resource-${extra.dataset_id}`}
                  checked={picked?.id === r.id}
                  disabled={!r.hosted}
                  onChange={() => {
                    setPicked(r)
                    if (!r.tabular_api) setMode('file')
                  }}
                />
                <span className="badge badge-secondary">{r.format}</span>
                <span>{r.title}</span>
                <span className="hint">
                  {size(r.filesize, locale)}
                  {r.tabular_api ? ` · ${t('tabularApi')}` : ''}
                  {!r.hosted ? ` · ${t('elsewhere')}` : ''}
                </span>
              </label>
            </li>
          ))}
        </ul>
        {picked && (
          <>
            {picked.tabular_api && <Profile resourceId={picked.id} />}
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'end' }}>
              <label className="label">
                {t('name')}
                <input
                  className="input"
                  value={name}
                  maxLength={100}
                  onChange={(e) => setName(e.target.value)}
                />
              </label>
              <label className="label">
                {t('mode')}
                <select
                  className="input"
                  value={mode}
                  onChange={(e) => setMode(e.target.value as 'file' | 'tabular_api')}
                >
                  <option value="file">{t('modeFile')}</option>
                  <option value="tabular_api" disabled={!picked.tabular_api}>
                    {t('modeTabular')}
                  </option>
                </select>
              </label>
              <button
                type="button"
                className="btn btn-primary"
                disabled={create.isPending || !name.trim()}
                onClick={() =>
                  create.mutate(
                    {
                      name: name.trim(),
                      connector: 'datagouv',
                      config: { dataset_id: extra.dataset_id, resource_id: picked.id, mode },
                      licence: extra.licence ?? null,
                    },
                    {
                      onSuccess: () => {
                        toast.success(t('added'))
                        onDone()
                      },
                      onError: (e: Error) => toast.error(e.message),
                    },
                  )
                }
              >
                {t('add')}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

// Search data.gouv.fr, pick a resource, add it as a data source (#311).
export function DatagouvSearch({ onDone }: { onDone: () => void }) {
  const t = useTranslations('sources.datagouv')
  const [text, setText] = useState('')
  const [query, setQuery] = useState('')
  useEffect(() => {
    const timer = setTimeout(() => setQuery(text.trim()), SEARCH_DELAY_MS)
    return () => clearTimeout(timer)
  }, [text])
  const { data, isFetching, error } = useDiscover('datagouv', query)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <input
        className="input"
        value={text}
        placeholder={t('placeholder')}
        aria-label={t('placeholder')}
        onChange={(e) => setText(e.target.value)}
      />
      {isFetching && <p className="hint">{t('searching')}</p>}
      {error && <p className="hint">{error.message}</p>}
      {data && data.candidates.length === 0 && <p className="hint">{t('none')}</p>}
      {(data?.candidates ?? []).map((c) => (
        <Result key={String(c.extra.dataset_id ?? c.title)} candidate={c} onDone={onDone} />
      ))}
    </div>
  )
}
