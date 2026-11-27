'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'
import { saveDataSourceSecret, testDataSource, type DataSource } from '@/api/sdk'
import { useCreateDataSource } from '@/hooks/use-data-sources'
import { PresetPicker } from './preset-picker'

// A worked example: the Géo API's communes of one département, no key.
const EXAMPLE = {
  url: 'https://geo.api.gouv.fr/departements/29/communes',
  params: { fields: 'nom,code,codesPostaux,population', format: 'json' },
  records_path: '$',
  pagination: { type: 'none' },
  producer: 'Géo API (DINUM)',
}

// One GET endpoint of a REST API (#313): its config as JSON, an optional key,
// then a test of the first page.
export function RestForm({ onDone }: { onDone: () => void }) {
  const t = useTranslations('sources.rest')
  const create = useCreateDataSource()
  const [name, setName] = useState('')
  const [licence, setLicence] = useState('')
  const [text, setText] = useState(JSON.stringify(EXAMPLE, null, 2))
  const [key, setKey] = useState('')
  const [created, setCreated] = useState<DataSource | null>(null)
  const [tested, setTested] = useState<{ records: number; columns: string[] } | null>(null)
  const [testing, setTesting] = useState(false)
  const [keyUrl, setKeyUrl] = useState<string | null>(null)

  let parsed: Record<string, unknown> | null = null
  let parseError = ''
  try {
    parsed = JSON.parse(text) as Record<string, unknown>
  } catch (err) {
    parseError = (err as Error).message
  }

  const runTest = async (source: DataSource) => {
    setTesting(true)
    try {
      const result = await testDataSource(source.id)
      setTested({ records: result.records, columns: result.columns })
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setTesting(false)
    }
  }

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!parsed) return
    create.mutate(
      {
        name: name.trim() || String(parsed.url ?? 'API'),
        connector: 'rest',
        config: parsed,
        licence: licence.trim() || null,
      },
      {
        onSuccess: async (source) => {
          if (key) {
            try {
              await saveDataSourceSecret(source.id, key)
            } catch (err) {
              toast.error((err as Error).message)
            }
          }
          setCreated(source)
          await runTest(source)
        },
        onError: (err: Error) => toast.error(err.message),
      },
    )
  }

  if (created) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <p>{t('created', { name: created.name })}</p>
        {testing && <p className="hint">{t('testing')}</p>}
        {tested && (
          <p className="hint">
            {t('tested', { records: tested.records, columns: tested.columns.join(', ') })}
          </p>
        )}
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            type="button"
            className="btn btn-outline"
            disabled={testing}
            onClick={() => void runTest(created)}
          >
            {t('test')}
          </button>
          <button type="button" className="btn btn-primary" onClick={onDone}>
            {t('done')}
          </button>
        </div>
      </div>
    )
  }

  return (
    <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <PresetPicker
        onPick={(picked) => {
          setName(picked.name)
          setLicence(picked.licence)
          setText(JSON.stringify(picked.config, null, 2))
          setKeyUrl(picked.needsKey ? picked.keyUrl : null)
        }}
      />
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
        {t('config')}
        <textarea
          className="input mono"
          rows={12}
          value={text}
          spellCheck={false}
          onChange={(e) => setText(e.target.value)}
        />
      </label>
      {parseError && <p className="hint">{t('badJson', { error: parseError })}</p>}
      <div className="hint">{t('configHint')}</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}>
        <label className="label">
          {t('licence')}
          <input
            className="input"
            value={licence}
            maxLength={200}
            onChange={(e) => setLicence(e.target.value)}
          />
        </label>
        <label className="label">
          {t('key')}
          <input
            className="input mono"
            type="password"
            autoComplete="off"
            value={key}
            maxLength={4096}
            onChange={(e) => setKey(e.target.value)}
          />
          {keyUrl && (
            <a className="hint underline" href={keyUrl} target="_blank" rel="noreferrer">
              {t('presetKeyWhere')}
            </a>
          )}
        </label>
      </div>
      <div>
        <button className="btn btn-primary" type="submit" disabled={!parsed || create.isPending}>
          {t('add')}
        </button>
      </div>
    </form>
  )
}
