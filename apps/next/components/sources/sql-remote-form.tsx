'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'
import { saveDataSourceSecret, testDataSource } from '@/api/sdk'
import { useCreateDataSource } from '@/hooks/use-data-sources'

// A table of the user's own PostgreSQL database (#322): read-only, on a host
// an admin allowed; the password is the data source's secret.
export function SqlRemoteForm({ onDone }: { onDone: () => void }) {
  const t = useTranslations('sources.sqlRemote')
  const create = useCreateDataSource()
  const [form, setForm] = useState({
    name: '',
    licence: '',
    host: '',
    port: '5432',
    database: '',
    user: '',
    schema: 'public',
    table: '',
    columns: '',
    max_rows: '100000',
  })
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [key]: e.target.value })

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    create.mutate(
      {
        name: form.name.trim() || `${form.database}.${form.table}`,
        connector: 'sql_remote',
        licence: form.licence.trim() || null,
        config: {
          host: form.host.trim(),
          port: Number(form.port) || 5432,
          database: form.database.trim(),
          user: form.user.trim(),
          schema: form.schema.trim() || 'public',
          table: form.table.trim(),
          columns: form.columns
            .split(',')
            .map((c) => c.trim())
            .filter(Boolean),
          max_rows: Number(form.max_rows) || 100000,
        },
      },
      {
        onSuccess: async (source) => {
          try {
            await saveDataSourceSecret(source.id, password)
            const tested = await testDataSource(source.id)
            toast.success(t('tested', { columns: tested.columns.join(', ') }))
            onDone()
          } catch (err) {
            toast.error((err as Error).message)
          } finally {
            setBusy(false)
          }
        },
        onError: (err: Error) => {
          setBusy(false)
          toast.error(err.message)
        },
      },
    )
  }

  const field = (key: keyof typeof form, label: string, props: Record<string, unknown> = {}) => (
    <label className="label">
      {label}
      <input className="input" value={form[key]} onChange={set(key)} {...props} />
    </label>
  )

  return (
    <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <p className="hint">{t('hint')}</p>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}>
        {field('name', t('name'), { maxLength: 100 })}
        {field('licence', t('licence'), { maxLength: 200 })}
        {field('host', t('host'), { required: true, placeholder: 'db.example.org' })}
        {field('port', t('port'), { type: 'number', min: 1, max: 65535 })}
        {field('database', t('database'), { required: true })}
        {field('user', t('user'), { required: true, autoComplete: 'off' })}
        <label className="label">
          {t('password')}
          <input
            className="input"
            type="password"
            autoComplete="off"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {field('schema', t('schema'))}
        {field('table', t('table'), { required: true })}
        {field('columns', t('columns'), { placeholder: t('allColumns') })}
        {field('max_rows', t('maxRows'), { type: 'number', min: 1, max: 1000000 })}
      </div>
      <div>
        <button className="btn btn-primary" type="submit" disabled={busy || !password}>
          {t('add')}
        </button>
      </div>
    </form>
  )
}
