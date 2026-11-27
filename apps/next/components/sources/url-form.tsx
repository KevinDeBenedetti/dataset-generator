'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'
import { saveDataSourceSecret } from '@/api/sdk'
import { useCreateDataSource } from '@/hooks/use-data-sources'

// A file at an https URL (#312), with an optional secret header.
export function UrlForm({ onDone }: { onDone: () => void }) {
  const t = useTranslations('sources.url')
  const create = useCreateDataSource()
  const [url, setUrl] = useState('')
  const [name, setName] = useState('')
  const [licence, setLicence] = useState('')
  const [producer, setProducer] = useState('')
  const [headerName, setHeaderName] = useState('')
  const [headerValue, setHeaderValue] = useState('')

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    create.mutate(
      {
        name: name.trim() || url,
        connector: 'url',
        config: {
          url: url.trim(),
          ...(producer.trim() ? { producer: producer.trim() } : {}),
          ...(headerName.trim() ? { header_name: headerName.trim() } : {}),
        },
        licence: licence.trim() || null,
      },
      {
        onSuccess: async (source) => {
          if (headerName.trim() && headerValue) {
            try {
              await saveDataSourceSecret(source.id, headerValue)
            } catch (err) {
              toast.error((err as Error).message)
              return
            }
          }
          toast.success(t('added'))
          onDone()
        },
        onError: (err: Error) => toast.error(err.message),
      },
    )
  }

  return (
    <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <label className="label">
        {t('url')}
        <input
          className="input mono"
          type="url"
          required
          placeholder="https://…"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
        />
      </label>
      <label className="label">
        {t('name')}
        <input
          className="input"
          value={name}
          maxLength={100}
          onChange={(e) => setName(e.target.value)}
        />
      </label>
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
          {t('producer')}
          <input
            className="input"
            value={producer}
            maxLength={200}
            onChange={(e) => setProducer(e.target.value)}
          />
        </label>
      </div>
      <details>
        <summary className="hint">{t('secretHeader')}</summary>
        <div
          style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8, marginTop: 8 }}
        >
          <label className="label">
            {t('headerName')}
            <input
              className="input mono"
              placeholder="Authorization"
              value={headerName}
              maxLength={64}
              onChange={(e) => setHeaderName(e.target.value)}
            />
          </label>
          <label className="label">
            {t('headerValue')}
            <input
              className="input mono"
              type="password"
              autoComplete="off"
              value={headerValue}
              maxLength={4096}
              onChange={(e) => setHeaderValue(e.target.value)}
            />
          </label>
        </div>
        <div className="hint">{t('secretHint')}</div>
      </details>
      <div>
        <button
          className="btn btn-primary"
          type="submit"
          disabled={!url.trim() || create.isPending}
        >
          {t('add')}
        </button>
      </div>
    </form>
  )
}
