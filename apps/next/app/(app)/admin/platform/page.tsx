'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'
import { usePlatform, useUpdatePlatform } from '@/hooks/use-admin'
import type { PlatformSwitch } from '@/api/sdk'

// The values of the choice switches, each with its label under `choices`.
const CHOICES = ['closed', 'orgs', 'open'] as const
type Choice = (typeof CHOICES)[number]
const isChoice = (value: string): value is Choice => (CHOICES as readonly string[]).includes(value)

function SwitchRow({ item }: { item: PlatformSwitch }) {
  const save = useUpdatePlatform()
  const t = useTranslations('admin.platform')
  const tc = useTranslations('common')
  const isList = Array.isArray(item.value)
  const choices = item.choices ?? null
  const [text, setText] = useState(isList ? (item.value as string[]).join(', ') : '')

  const submit = (value: unknown) =>
    save.mutate(
      { [item.key]: value },
      { onSuccess: () => toast.success(t('saved')), onError: (e: Error) => toast.error(e.message) },
    )

  return (
    <div className="field">
      <label className="label" htmlFor={`switch-${item.key}`}>
        {item.label}{' '}
        <span className={`badge badge-${item.overridden ? 'info' : 'secondary'}`}>
          {item.overridden ? t('setHere') : t('envDefault')}
        </span>
      </label>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        {choices ? (
          <select
            id={`switch-${item.key}`}
            className="input"
            value={String(item.value)}
            disabled={save.isPending}
            onChange={(e) => submit(e.target.value)}
          >
            {choices.map((choice) => (
              <option key={choice} value={choice}>
                {isChoice(choice) ? t(`choices.${choice}`) : choice}
              </option>
            ))}
          </select>
        ) : isList ? (
          <>
            <input
              id={`switch-${item.key}`}
              className="input mono"
              value={text}
              placeholder={t('commaSeparated')}
              onChange={(e) => setText(e.target.value)}
            />
            <button
              className="btn btn-outline"
              type="button"
              disabled={save.isPending}
              onClick={() =>
                submit(
                  text
                    .split(',')
                    .map((v) => v.trim())
                    .filter(Boolean),
                )
              }
            >
              {tc('save')}
            </button>
          </>
        ) : (
          <button
            id={`switch-${item.key}`}
            className={`btn ${item.value ? 'btn-primary' : 'btn-outline'}`}
            type="button"
            disabled={save.isPending}
            onClick={() => submit(!item.value)}
          >
            {item.value ? t('on') : t('off')}
          </button>
        )}
        {item.overridden && (
          <button
            className="btn btn-outline btn-sm"
            type="button"
            disabled={save.isPending}
            onClick={() => submit(null)}
          >
            {t('reset')}
          </button>
        )}
      </div>
    </div>
  )
}

export default function AdminPlatformPage() {
  const { data, error } = usePlatform()
  const t = useTranslations('admin.platform')
  return (
    <div className="card">
      <div className="card-head">
        <div>
          <div className="card-title">{t('title')}</div>
          <div className="card-desc">{t('description')}</div>
        </div>
      </div>
      <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        {error && <p className="hint">{error.message}</p>}
        {(data?.settings ?? []).map((item) => (
          // Keyed by value: a saved change remounts the row with fresh input state.
          <SwitchRow key={`${item.key}:${JSON.stringify(item.value)}`} item={item} />
        ))}
      </div>
    </div>
  )
}
