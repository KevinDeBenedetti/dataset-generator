'use client'

import { useState } from 'react'
import { toast } from 'sonner'
import { usePlatform, useUpdatePlatform } from '@/hooks/use-admin'
import type { PlatformSwitch } from '@/api/sdk'

function SwitchRow({ item }: { item: PlatformSwitch }) {
  const save = useUpdatePlatform()
  const isList = Array.isArray(item.value)
  const [text, setText] = useState(isList ? (item.value as string[]).join(', ') : '')

  const submit = (value: unknown) =>
    save.mutate(
      { [item.key]: value },
      { onSuccess: () => toast.success('Saved'), onError: (e: Error) => toast.error(e.message) },
    )

  return (
    <div className="field">
      <label className="label" htmlFor={`switch-${item.key}`}>
        {item.label}{' '}
        <span className={`badge badge-${item.overridden ? 'info' : 'secondary'}`}>
          {item.overridden ? 'set here' : 'env default'}
        </span>
      </label>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        {isList ? (
          <>
            <input
              id={`switch-${item.key}`}
              className="input mono"
              value={text}
              placeholder="comma-separated"
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
              Save
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
            {item.value ? 'On' : 'Off'}
          </button>
        )}
        {item.overridden && (
          <button
            className="btn btn-outline btn-sm"
            type="button"
            disabled={save.isPending}
            onClick={() => submit(null)}
          >
            Reset to env
          </button>
        )}
      </div>
    </div>
  )
}

export default function AdminPlatformPage() {
  const { data, error } = usePlatform()
  return (
    <div className="card">
      <div className="card-head">
        <div>
          <div className="card-title">Platform</div>
          <div className="card-desc">
            Switches stored in the database override the environment. Other replicas pick changes up
            within a few seconds.
          </div>
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
