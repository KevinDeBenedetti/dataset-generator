'use client'

import type { ReactNode } from 'react'
import { type Every, type ScheduleForm, type ScheduleSkip, skipNotice } from './schedule-state'

const EVERY: { value: Every; label: string }[] = [
  { value: '', label: 'Only when I start it' },
  { value: 'day', label: 'Every day' },
  { value: 'week', label: 'Every Monday' },
  { value: 'month', label: 'The 1st of every month' },
]

/** When something runs by itself: a preset, a time of day (UTC) and whether
 * a scheduled run publishes. Its owner saves each change. */
export function SchedulePicker({
  id,
  form,
  disabled,
  publishLabel,
  skipped,
  children,
  onChange,
}: {
  id: string
  form: ScheduleForm
  disabled?: boolean
  publishLabel: string
  /** Why the latest scheduled time started no run, when it didn't. */
  skipped?: ScheduleSkip | null
  /** The hint under the publish toggle, shown once a preset is set. */
  children?: ReactNode
  onChange: (patch: Partial<ScheduleForm>) => void
}) {
  const notice = skipNotice(skipped)
  return (
    <div className="gh-recipe-row gh-schedule">
      <div className="field">
        <label className="label" htmlFor={id}>
          Regenerate
        </label>
        <div className="gh-inline">
          <select
            id={id}
            className="select"
            value={form.every}
            disabled={disabled}
            onChange={(e) => onChange({ every: e.target.value as Every })}
          >
            {EVERY.map((e) => (
              <option key={e.value} value={e.value}>
                {e.label}
              </option>
            ))}
          </select>
          {form.every && (
            <input
              type="time"
              className="input"
              aria-label="Time (UTC)"
              value={form.time}
              disabled={disabled}
              onChange={(e) => onChange({ time: e.target.value || '03:00' })}
            />
          )}
        </div>
      </div>
      {form.every && (
        <div className="gh-schedule-notes">
          <label className="gh-toggle">
            <input
              type="checkbox"
              checked={form.publish}
              disabled={disabled}
              onChange={(e) => onChange({ publish: e.target.checked })}
            />
            {publishLabel}
          </label>
          <span className="hint">{children}</span>
          {notice && <span className="hint job-config-hint">{notice}</span>}
        </div>
      )}
    </div>
  )
}
