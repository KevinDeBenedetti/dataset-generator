'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'
import type { DraftPair, JobRunOut } from '@/api/types'
import { Icon } from '@/components/app/icon'
import { datasetHref, formatCount, formatPercent } from '@/components/hub/format'
import { useDraftChecks, useJobRun, usePublishJobRun } from '@/hooks'
import { cn } from '@/lib/utils'

type Section = 'new' | 'review' | 'removed'
type Edit = { question: string; answer: string }

// Answers this far from their source, or graded this low by the LLM, are
// worth a second look (the server holds grades below 0.6 for review).
const LOW_GROUNDING = 0.6
const LOW_GRADE = 0.6

function Score({ label, value }: { label: string; value: number | null | undefined }) {
  if (value == null) return null
  const low =
    (label === 'grounding' && value < LOW_GROUNDING) || (label === 'grade' && value < LOW_GRADE)
  return (
    <span className={cn('tag', low && 'gh-low')}>
      {label} {formatPercent(value, 1)}
    </span>
  )
}

function PairCard({
  pair,
  included,
  editable,
  edit,
  flag,
  onToggle,
  onEdit,
}: {
  pair: DraftPair
  included: boolean | null
  editable: boolean
  edit: Edit | undefined
  flag?: string
  onToggle?: () => void
  onEdit?: (edit: Edit | null) => void
}) {
  const [draft, setDraft] = useState<Edit | null>(null)
  const shown = edit ?? { question: pair.question, answer: pair.answer }
  return (
    <li className={cn('gh-pair', included === false && 'is-out')}>
      <div className="gh-pair-head">
        {included !== null && onToggle && (
          <input
            type="checkbox"
            checked={included}
            onChange={onToggle}
            aria-label={included ? 'Leave this pair out' : 'Include this pair'}
          />
        )}
        {pair.category && <span className="tag">{pair.category}</span>}
        {pair.repo && <span className="tag">{pair.repo}</span>}
        <Score label="confidence" value={pair.confidence} />
        <Score label="grounding" value={pair.grounding} />
        <Score label="grade" value={pair.judge} />
        {pair.judge_note && (pair.judge ?? 1) < LOW_GRADE && (
          <span className="tag gh-low" title="The grader's reason">
            {pair.judge_note}
          </span>
        )}
        {flag && <span className="tag gh-low">fails your rules: {flag}</span>}
        {edit && <span className="badge badge-info">Edited</span>}
        {editable && onEdit && !draft && (
          <span className="gh-pair-actions">
            {edit && (
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => onEdit(null)}>
                Undo edit
              </button>
            )}
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setDraft(shown)}>
              <Icon name="edit" />
              Edit
            </button>
          </span>
        )}
      </div>
      {draft && onEdit ? (
        <div className="gh-pair-edit">
          <label className="label" htmlFor={`q-${pair.id}`}>
            Question
          </label>
          <textarea
            id={`q-${pair.id}`}
            className="textarea"
            rows={2}
            maxLength={2000}
            value={draft.question}
            onChange={(e) => setDraft({ ...draft, question: e.target.value })}
          />
          <label className="label" htmlFor={`a-${pair.id}`}>
            Answer
          </label>
          <textarea
            id={`a-${pair.id}`}
            className="textarea"
            rows={4}
            maxLength={10000}
            value={draft.answer}
            onChange={(e) => setDraft({ ...draft, answer: e.target.value })}
          />
          <div className="gh-pair-actions">
            <button
              type="button"
              className="btn btn-primary btn-sm"
              disabled={!draft.question.trim() || !draft.answer.trim()}
              onClick={() => {
                const unchanged =
                  draft.question.trim() === pair.question && draft.answer.trim() === pair.answer
                onEdit(
                  unchanged
                    ? null
                    : { question: draft.question.trim(), answer: draft.answer.trim() },
                )
                setDraft(null)
              }}
            >
              Keep this version
            </button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setDraft(null)}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <>
          <p className="gh-pair-q">{shown.question}</p>
          <p className="gh-pair-a">{shown.answer}</p>
        </>
      )}
    </li>
  )
}

/** ``set`` with ``id`` added or removed. */
function toggled(set: Set<string>, id: string): Set<string> {
  const next = new Set(set)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  return next
}

function Waiting({ run }: { run: JobRunOut }) {
  const { done = 0, total = 0, label = '' } = run.progress ?? {}
  return (
    <div className="card hub-loading">
      <Icon name="loader" className="animate-spin" />
      {run.status === 'queued'
        ? 'Queued — waiting for a worker.'
        : total > 0
          ? `Generating… ${done}/${total} repos${label ? ` · ${label}` : ''}`
          : 'Reading GitHub…'}{' '}
      The draft shows up here when it is ready.
    </div>
  )
}

/** Review a run's draft, then publish exactly that to Hugging Face. */
export function DraftReview({ runId }: { runId: string }) {
  const router = useRouter()
  const run = useJobRun(runId)
  const publish = usePublishJobRun(runId)
  const [section, setSection] = useState<Section>('new')
  const [excluded, setExcluded] = useState<Set<string>>(new Set())
  const [promoted, setPromoted] = useState<Set<string>>(new Set())
  const [edits, setEdits] = useState<Record<string, Edit>>({})
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState('')
  const [repo, setRepo] = useState('')
  const [lowOnly, setLowOnly] = useState(false)
  const [flaggedOnly, setFlaggedOnly] = useState(false)
  const checks = useDraftChecks(runId, run.data?.status === 'succeeded')
  const flagged = checks.data?.flagged ?? {}

  const preview = run.data?.preview
  const pairs = useMemo(() => {
    if (!preview) return { new: [], review: [], removed: [] } as Record<Section, DraftPair[]>
    return { new: preview.new, review: preview.review, removed: preview.removed ?? [] }
  }, [preview])
  const all = [...pairs.new, ...pairs.review, ...pairs.removed]
  const categories = [...new Set(all.map((p) => p.category).filter(Boolean) as string[])].toSorted()
  const repos = [...new Set(all.map((p) => p.repo).filter(Boolean) as string[])].toSorted()
  const needle = query.trim().toLowerCase()
  const visible = pairs[section].filter(
    (p) =>
      (!category || p.category === category) &&
      (!repo || p.repo === repo) &&
      (!lowOnly || (p.grounding ?? 1) < LOW_GROUNDING) &&
      (!flaggedOnly || Boolean(flagged[p.id ?? ''])) &&
      (!needle || `${p.question} ${p.answer}`.toLowerCase().includes(needle)),
  )

  if (run.isPending) {
    return (
      <div className="card hub-loading" aria-busy="true">
        <Icon name="loader" className="animate-spin" />
        Loading the draft…
      </div>
    )
  }
  if (run.error) return <p className="hub-error">{run.error.message}</p>
  const data = run.data
  // Back to where the draft was started: a recipe's GitHub page, a resume's
  // page, else the drafts list.
  const back =
    data.job === 'github-recipe'
      ? { href: '/github', label: 'GitHub' }
      : data.job === 'resume-qa'
        ? { href: '/resume', label: 'Resume' }
        : { href: '/drafts', label: 'Drafts' }
  const recipeName =
    (data.options?.recipe as { name?: string } | undefined)?.name ??
    (data.options?.title as string | undefined) ??
    'Draft'
  const target = preview?.repo_id ?? ''

  const header = (
    <>
      <Link href={back.href} className="btn btn-ghost btn-sm hub-back">
        <Icon name="chevronLeft" />
        {back.label}
      </Link>
      <div className="page-head">
        <div>
          <h1 className="page-title">Review: {recipeName}</h1>
          <p className="page-sub">
            {target ? (
              <>
                Publishes to <span className="mono">{target}</span>
              </>
            ) : null}
            {data.model_ref ? ` · generated with ${data.model_ref}` : ''}
          </p>
        </div>
      </div>
    </>
  )

  if (data.status === 'queued' || data.status === 'running') {
    return (
      <div className="hub-page gh-page">
        {header}
        <Waiting run={data} />
      </div>
    )
  }
  if (data.status === 'published' || data.status === 'publishing') {
    return (
      <div className="hub-page gh-page">
        {header}
        <div className="card hub-empty">
          <span className="cell-ic ic-lg">
            <Icon name="check" className="ic-lg" />
          </span>
          <div>
            <div className="card-title">
              {data.status === 'publishing' ? 'Publishing…' : 'Published'}
            </div>
            <p className="card-desc">
              {data.published_at ? new Date(data.published_at).toLocaleString() : ''}
            </p>
          </div>
          {target && (
            <Link className="btn btn-primary" href={datasetHref(target)}>
              Open the dataset
            </Link>
          )}
        </div>
      </div>
    )
  }
  if (!preview || data.status !== 'succeeded') {
    return (
      <div className="hub-page gh-page">
        {header}
        <p className="hub-error">
          {data.status === 'failed'
            ? `The generation failed: ${data.error ?? 'unknown error'}`
            : `This run has no draft to review (${data.status}).`}
        </p>
      </div>
    )
  }

  const included = preview.new.length - excluded.size + promoted.size
  const total = preview.kept + included
  const editCount = Object.keys(edits).length
  const errors = data.result?.errors ?? []

  const setEdit = (id: string, edit: Edit | null) => {
    const next = { ...edits }
    if (edit) next[id] = edit
    else delete next[id]
    setEdits(next)
  }
  const newIds = new Set(preview.new.map((p) => p.id ?? ''))
  const byId = new Map(all.map((p) => [p.id ?? '', p]))
  // Pairs that go out: new ones not left out, held-out ones taken in.
  const goesOut = (id: string) => (newIds.has(id) && !excluded.has(id)) || promoted.has(id)
  const doPublish = () =>
    publish.mutate(
      {
        exclude: [...excluded],
        promote: [...promoted],
        // Only edits of pairs that go out: a left-out pair's edit is moot.
        edits: Object.fromEntries(Object.entries(edits).filter(([id]) => goesOut(id))),
      },
      {
        onSuccess: () => {
          toast.success(`Published ${total} pairs to ${target}`)
          router.push(datasetHref(target))
        },
        onError: (error) => toast.error(error.message),
      },
    )

  const sections: [Section, string, number][] = [
    ['new', 'New', preview.new.length],
    ['review', 'Held out', preview.review.length],
    ['removed', 'Removed', (preview.removed ?? []).length],
  ]

  return (
    <div className="hub-page gh-page">
      {header}

      <div className="stat-grid hub-stats">
        <div className="card stat">
          <div className="stat-label">Will be published</div>
          <div className="stat-val">{formatCount(total)}</div>
          <div className="stat-delta">{formatCount(preview.kept)} kept unchanged</div>
        </div>
        <div className="card stat">
          <div className="stat-label">New pairs</div>
          <div className="stat-val">
            {formatCount(preview.new.length - excluded.size)}
            <span className="muted"> / {formatCount(preview.new.length)}</span>
          </div>
        </div>
        <div className="card stat">
          <div className="stat-label">Held out, taken in</div>
          <div className="stat-val">
            {formatCount(promoted.size)}
            <span className="muted"> / {formatCount(preview.review.length)}</span>
          </div>
          <div className="stat-delta">answer far from its source</div>
        </div>
        <div className="card stat">
          <div className="stat-label">Removed from the dataset</div>
          <div className="stat-val">{formatCount((preview.removed ?? []).length)}</div>
          <div className="stat-delta">sources deselected or gone</div>
        </div>
      </div>

      {errors.length > 0 && (
        <details className="card hub-meta">
          <summary>
            <Icon name="alert" className="ic-sm" />
            {errors.length} problem(s) while generating
            <span className="muted">the affected sources were skipped</span>
          </summary>
          <ul className="gh-errors">
            {errors.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        </details>
      )}

      {checks.data && checks.data.duplicates.length > 0 && (
        <details className="card hub-meta" open>
          <summary>
            <Icon name="copy" className="ic-sm" />
            {checks.data.duplicates.length} possible duplicate(s)
            <span className="muted">same question, close answers</span>
          </summary>
          <ul className="gh-dupes">
            {checks.data.duplicates.map((d) => {
              const second = byId.get(d.second)
              const out = excluded.has(d.second) || !newIds.has(d.second)
              return (
                <li key={`${d.first}-${d.second}`}>
                  <span className="mono muted">{formatPercent(d.similarity, 1)}</span>
                  <span className="gh-dupe-q">
                    {byId.get(d.first)?.question} ≈ {second?.question}
                  </span>
                  {newIds.has(d.second) && (
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      disabled={out}
                      onClick={() => setExcluded(toggled(excluded, d.second))}
                    >
                      {out ? 'Left out' : 'Leave out the second'}
                    </button>
                  )}
                </li>
              )
            })}
          </ul>
        </details>
      )}

      <div className="hub-toolbar">
        <fieldset className="tabs">
          <legend className="sr-only">Pairs</legend>
          {sections.map(([key, label, count]) => (
            <button
              key={key}
              type="button"
              className={cn('tab', section === key && 'active')}
              aria-pressed={section === key}
              onClick={() => setSection(key)}
            >
              {label} <span className="mono muted">{count}</span>
            </button>
          ))}
        </fieldset>
        <label className="hub-search">
          <Icon name="search" />
          <input
            type="search"
            placeholder="Search questions and answers"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <select
          className="select gh-lang"
          aria-label="Category"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
        >
          <option value="">All categories</option>
          {categories.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <select
          className="select gh-lang"
          aria-label="Repo"
          value={repo}
          onChange={(e) => setRepo(e.target.value)}
        >
          <option value="">All repos</option>
          {repos.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
        <label className="gh-toggle">
          <input type="checkbox" checked={lowOnly} onChange={(e) => setLowOnly(e.target.checked)} />
          Low grounding
        </label>
        <label className="gh-toggle">
          <input
            type="checkbox"
            checked={flaggedOnly}
            onChange={(e) => setFlaggedOnly(e.target.checked)}
          />
          Fails your rules
        </label>
      </div>

      {section === 'removed' && visible.length > 0 && (
        <p className="hint">
          These pairs are in the published dataset and not in this draft: publishing deletes them.
        </p>
      )}
      {visible.length === 0 ? (
        <p className="muted hub-none">Nothing here.</p>
      ) : (
        <ul className="gh-pairs">
          {visible.map((pair) => {
            const id = pair.id ?? ''
            if (section === 'removed') {
              return (
                <PairCard key={id} pair={pair} included={null} editable={false} edit={undefined} />
              )
            }
            const isNew = section === 'new'
            const on = isNew ? !excluded.has(id) : promoted.has(id)
            return (
              <PairCard
                key={id}
                pair={pair}
                included={on}
                editable={on}
                edit={edits[id]}
                flag={flagged[id]}
                onToggle={() =>
                  isNew ? setExcluded(toggled(excluded, id)) : setPromoted(toggled(promoted, id))
                }
                onEdit={(edit) => setEdit(id, edit)}
              />
            )
          })}
        </ul>
      )}

      <div className="gh-publish-bar">
        <span className="hint">
          {formatCount(total)} pairs
          {editCount > 0 ? ` · ${editCount} edited` : ''} · private repo{' '}
          <span className="mono">{target}</span>
        </span>
        <button
          type="button"
          className="btn btn-primary"
          disabled={publish.isPending || total === 0}
          onClick={doPublish}
        >
          <Icon name={publish.isPending ? 'loader' : 'upload'} />
          Publish to Hugging Face
        </button>
      </div>
    </div>
  )
}
