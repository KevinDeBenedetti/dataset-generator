'use client'

import { useEffect, useRef } from 'react'
import { toast } from 'sonner'
import type { HubRepoRef, HubSplitQuery } from '@/api/sdk'
import type { HubFeature, HubQaColumns, HubRow } from '@/api/types'
import { Icon } from '@/components/app/icon'
import { useHubRow } from '@/hooks'
import { formatValue, isHttpUrl } from './format'

function FieldValue({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className="hub-null">null</span>
  if (typeof value === 'boolean') return <span className="tag">{String(value)}</span>
  if (typeof value === 'number') return <span className="mono">{formatValue(value)}</span>
  if (typeof value === 'string') {
    if (value === '') return <span className="hub-null">empty</span>
    if (isHttpUrl(value)) {
      return (
        <a href={value} target="_blank" rel="noopener noreferrer" className="hub-link">
          {value}
        </a>
      )
    }
    return <span className="hub-prose">{value}</span>
  }
  if (Array.isArray(value) && value.every((item) => typeof item !== 'object' || item === null)) {
    return (
      <span className="hub-chips">
        {value.map((item, i) => (
          // A list's items have no identity but their position.
          // oxlint-disable-next-line react/no-array-index-key
          <span key={i} className="tag">
            {String(item)}
          </span>
        ))}
      </span>
    )
  }
  return <pre className="hub-pre">{JSON.stringify(value, null, 2)}</pre>
}

/** One row in full, beside the list it was opened from. */
export function RowDrawer({
  repo,
  splitQuery,
  split,
  row,
  features,
  qa,
  onClose,
  onPrev,
  onNext,
}: {
  repo: HubRepoRef
  splitQuery: HubSplitQuery
  split: string
  row: HubRow
  features: HubFeature[]
  qa: HubQaColumns | null
  onClose: () => void
  onPrev: (() => void) | null
  onNext: (() => void) | null
}) {
  // The page's copy has long cells cut: fetch the whole row only then.
  const cut = (row.truncated_cells ?? []).length > 0
  const full = useHubRow(repo, cut ? row.row_idx : null, splitQuery)
  const values = full.data?.row ?? row.row
  const dialogRef = useRef<HTMLDialogElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)
  // The listener above is attached once; it calls the latest onClose.
  const closeLatest = useRef(onClose)
  useEffect(() => {
    closeLatest.current = onClose
  }, [onClose])

  // A native modal dialog: focus stays inside, the page behind is inert, and
  // Esc arrives as a ``cancel`` event (routed to onClose so the URL follows).
  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (!dialog.open) dialog.showModal()
    closeRef.current?.focus()
    // A click on the backdrop reaches the dialog itself (its content fills
    // it): close, like Esc and the close button — keyboard users have both.
    const onBackdrop = (event: MouseEvent) => {
      if (event.target === dialog) closeLatest.current()
    }
    dialog.addEventListener('click', onBackdrop)
    return () => dialog.removeEventListener('click', onBackdrop)
  }, [])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLElement && event.target.closest('input, textarea, select')) {
        return
      }
      if ((event.key === 'ArrowLeft' || event.key === 'k') && onPrev) onPrev()
      else if ((event.key === 'ArrowRight' || event.key === 'j') && onNext) onNext()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onPrev, onNext])

  const qaColumns = new Set(qa ? [qa.question, qa.answer, qa.context].filter(Boolean) : [])
  const others = features.filter((f) => !qaColumns.has(f.name))

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(values, null, 2))
      toast.success(`Row ${row.row_idx} copied as JSON`)
    } catch {
      toast.error('The browser refused access to the clipboard')
    }
  }

  return (
    <dialog
      ref={dialogRef}
      className="hub-drawer"
      aria-labelledby="hub-row-title"
      onCancel={(event) => {
        event.preventDefault()
        onClose()
      }}
    >
      <div className="hub-drawer-inner">
        <header className="hub-drawer-head">
          <div>
            <h2 id="hub-row-title" className="card-title">
              Row {row.row_idx}
            </h2>
            <div className="hint">
              {split} split · ←/→ to move, Esc to close
              {cut && full.isPending && ' · loading the full row…'}
            </div>
          </div>
          <div className="hub-drawer-actions">
            <button
              type="button"
              className="icon-btn"
              onClick={onPrev ?? undefined}
              disabled={!onPrev}
              aria-label="Previous row"
            >
              <Icon name="chevronLeft" />
            </button>
            <button
              type="button"
              className="icon-btn"
              onClick={onNext ?? undefined}
              disabled={!onNext}
              aria-label="Next row"
            >
              <Icon name="chevronRight" />
            </button>
            <button type="button" className="icon-btn" onClick={copy} aria-label="Copy as JSON">
              <Icon name="copy" />
            </button>
            <button
              ref={closeRef}
              type="button"
              className="icon-btn"
              onClick={onClose}
              aria-label="Close"
            >
              <Icon name="x" />
            </button>
          </div>
        </header>

        <div className="hub-drawer-body">
          {qa && (
            <section className="hub-qa-full">
              <h3>Question</h3>
              <p className="hub-prose hub-qa-q">{String(values[qa.question] ?? '')}</p>
              <h3>Answer</h3>
              <p className="hub-prose">{String(values[qa.answer] ?? '')}</p>
              {qa.context && values[qa.context] != null && values[qa.context] !== '' && (
                <>
                  <h3>Context</h3>
                  <p className="hub-prose hub-context">{String(values[qa.context])}</p>
                </>
              )}
            </section>
          )}
          {others.length > 0 && (
            <dl className="hub-fields">
              {others.map((f) => (
                <div key={f.name} className="hub-field">
                  <dt>
                    <span className="mono">{f.name}</span>
                    <span className="hub-th-kind">{f.kind}</span>
                  </dt>
                  <dd>
                    <FieldValue value={values[f.name]} />
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      </div>
    </dialog>
  )
}
