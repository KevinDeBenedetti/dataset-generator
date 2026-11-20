'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useMemo, useState } from 'react'
import { useLocale, useTranslations } from 'next-intl'
import { toast } from 'sonner'
import type { DraftPair, JobRunOut } from '@/api/types'
import { Icon } from '@/components/app/icon'
import { datasetHref, formatCount, formatPercent } from '@/components/hub/format'
import { useDraftChecks, useJobRun, usePublishJobRun } from '@/hooks'
import { rich } from '@/lib/rich'
import { cn } from '@/lib/utils'

type Section = 'new' | 'review' | 'removed'
type Edit = { question: string; answer: string }

// Answers this far from their source, or graded this low by the LLM, are
// worth a second look (the server holds grades below 0.6 for review).
const LOW_GROUNDING = 0.6
const LOW_GRADE = 0.6

type ScoreKind = 'confidence' | 'grounding' | 'grade'

// The label is the `review.scores.<kind>` message.
function Score({ kind, value }: { kind: ScoreKind; value: number | null | undefined }) {
  const t = useTranslations('review')
  const locale = useLocale()
  if (value == null) return null
  const low =
    (kind === 'grounding' && value < LOW_GROUNDING) || (kind === 'grade' && value < LOW_GRADE)
  return (
    <span className={cn('tag', low && 'gh-low')}>
      {t(`scores.${kind}`)} {formatPercent(value, 1, locale)}
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
  const t = useTranslations('review')
  const tc = useTranslations('common')
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
            aria-label={included ? t('pair.leaveOut') : t('pair.include')}
          />
        )}
        {pair.category && <span className="tag">{pair.category}</span>}
        {pair.repo && <span className="tag">{pair.repo}</span>}
        <Score kind="confidence" value={pair.confidence} />
        <Score kind="grounding" value={pair.grounding} />
        <Score kind="grade" value={pair.judge} />
        {pair.judge_note && (pair.judge ?? 1) < LOW_GRADE && (
          <span className="tag gh-low" title={t('pair.graderReason')}>
            {pair.judge_note}
          </span>
        )}
        {flag && <span className="tag gh-low">{t('pair.failsRules', { reason: flag })}</span>}
        {edit && <span className="badge badge-info">{t('pair.edited')}</span>}
        {editable && onEdit && !draft && (
          <span className="gh-pair-actions">
            {edit && (
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => onEdit(null)}>
                {t('pair.undoEdit')}
              </button>
            )}
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setDraft(shown)}>
              <Icon name="edit" />
              {tc('edit')}
            </button>
          </span>
        )}
      </div>
      {draft && onEdit ? (
        <div className="gh-pair-edit">
          <label className="label" htmlFor={`q-${pair.id}`}>
            {t('pair.question')}
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
            {t('pair.answer')}
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
              {t('pair.keep')}
            </button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setDraft(null)}>
              {tc('cancel')}
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
  const t = useTranslations('review')
  const { done = 0, total = 0, label = '' } = run.progress ?? {}
  return (
    <div className="card hub-loading">
      <Icon name="loader" className="animate-spin" />
      {run.status === 'queued'
        ? t('waiting.queued')
        : total > 0
          ? `${t('waiting.generating', { done, total })}${label ? ` · ${label}` : ''}`
          : t('waiting.reading')}{' '}
      {t('waiting.ready')}
    </div>
  )
}

/** Review a run's draft, then publish exactly that to Hugging Face. */
export function DraftReview({ runId }: { runId: string }) {
  const t = useTranslations('review')
  const locale = useLocale()
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
        {t('loading')}
      </div>
    )
  }
  if (run.error) return <p className="hub-error">{run.error.message}</p>
  const data = run.data
  // Back to where the draft was started: a recipe's GitHub page, a resume's
  // page, else the drafts list.
  const back =
    data.job === 'github-recipe'
      ? { href: '/github', label: t('back.github') }
      : data.job === 'resume-qa'
        ? { href: '/resume', label: t('back.resume') }
        : { href: '/drafts', label: t('back.drafts') }
  const recipeName =
    (data.options?.recipe as { name?: string } | undefined)?.name ??
    (data.options?.title as string | undefined) ??
    t('fallbackName')
  const target = preview?.repo_id ?? ''

  const header = (
    <>
      <Link href={back.href} className="btn btn-ghost btn-sm hub-back">
        <Icon name="chevronLeft" />
        {back.label}
      </Link>
      <div className="page-head">
        <div>
          <h1 className="page-title">{t('title', { name: recipeName })}</h1>
          <p className="page-sub">
            {target ? t.rich('publishesTo', { ...rich, target }) : null}
            {data.model_ref ? ` · ${t('generatedWith', { model: data.model_ref })}` : ''}
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
              {data.status === 'publishing' ? t('publishing') : t('published')}
            </div>
            <p className="card-desc">
              {data.published_at ? new Date(data.published_at).toLocaleString(locale) : ''}
            </p>
          </div>
          {target && (
            <Link className="btn btn-primary" href={datasetHref(target)}>
              {t('openDataset')}
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
            ? t('failed', { error: data.error ?? t('unknownError') })
            : t('noDraft', { status: data.status })}
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
          toast.success(t('publishedToast', { count: total, repo: target }))
          router.push(datasetHref(target))
        },
        onError: (error) => toast.error(error.message),
      },
    )

  // The tab labels are the `review.sections.<key>` messages.
  const sections: [Section, number][] = [
    ['new', preview.new.length],
    ['review', preview.review.length],
    ['removed', (preview.removed ?? []).length],
  ]

  return (
    <div className="hub-page gh-page">
      {header}

      <div className="stat-grid hub-stats">
        <div className="card stat">
          <div className="stat-label">{t('stats.total')}</div>
          <div className="stat-val">{formatCount(total, locale)}</div>
          <div className="stat-delta">
            {t('stats.kept', { count: formatCount(preview.kept, locale) })}
          </div>
        </div>
        <div className="card stat">
          <div className="stat-label">{t('stats.new')}</div>
          <div className="stat-val">
            {formatCount(preview.new.length - excluded.size, locale)}
            <span className="muted"> / {formatCount(preview.new.length, locale)}</span>
          </div>
        </div>
        <div className="card stat">
          <div className="stat-label">{t('stats.promoted')}</div>
          <div className="stat-val">
            {formatCount(promoted.size, locale)}
            <span className="muted"> / {formatCount(preview.review.length, locale)}</span>
          </div>
          <div className="stat-delta">{t('stats.promotedHint')}</div>
        </div>
        <div className="card stat">
          <div className="stat-label">{t('stats.removed')}</div>
          <div className="stat-val">{formatCount((preview.removed ?? []).length, locale)}</div>
          <div className="stat-delta">{t('stats.removedHint')}</div>
        </div>
      </div>

      {errors.length > 0 && (
        <details className="card hub-meta">
          <summary>
            <Icon name="alert" className="ic-sm" />
            {t('problems.title', { count: errors.length })}
            <span className="muted">{t('problems.hint')}</span>
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
            {t('duplicates.title', { count: checks.data.duplicates.length })}
            <span className="muted">{t('duplicates.hint')}</span>
          </summary>
          <ul className="gh-dupes">
            {checks.data.duplicates.map((d) => {
              const second = byId.get(d.second)
              const out = excluded.has(d.second) || !newIds.has(d.second)
              return (
                <li key={`${d.first}-${d.second}`}>
                  <span className="mono muted">{formatPercent(d.similarity, 1, locale)}</span>
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
                      {out ? t('duplicates.leftOut') : t('duplicates.leaveOut')}
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
          <legend className="sr-only">{t('filters.pairs')}</legend>
          {sections.map(([key, count]) => (
            <button
              key={key}
              type="button"
              className={cn('tab', section === key && 'active')}
              aria-pressed={section === key}
              onClick={() => setSection(key)}
            >
              {t(`sections.${key}`)} <span className="mono muted">{count}</span>
            </button>
          ))}
        </fieldset>
        <label className="hub-search">
          <Icon name="search" />
          <input
            type="search"
            placeholder={t('filters.search')}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <select
          className="select gh-lang"
          aria-label={t('filters.category')}
          value={category}
          onChange={(e) => setCategory(e.target.value)}
        >
          <option value="">{t('filters.allCategories')}</option>
          {categories.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <select
          className="select gh-lang"
          aria-label={t('filters.repo')}
          value={repo}
          onChange={(e) => setRepo(e.target.value)}
        >
          <option value="">{t('filters.allRepos')}</option>
          {repos.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
        <label className="gh-toggle">
          <input type="checkbox" checked={lowOnly} onChange={(e) => setLowOnly(e.target.checked)} />
          {t('filters.lowGrounding')}
        </label>
        <label className="gh-toggle">
          <input
            type="checkbox"
            checked={flaggedOnly}
            onChange={(e) => setFlaggedOnly(e.target.checked)}
          />
          {t('filters.failsRules')}
        </label>
      </div>

      {section === 'removed' && visible.length > 0 && <p className="hint">{t('removedHint')}</p>}
      {visible.length === 0 ? (
        <p className="muted hub-none">{t('empty')}</p>
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
          {t('bar.pairs', { count: total, formatted: formatCount(total, locale) })}
          {editCount > 0 ? ` · ${t('bar.edited', { count: editCount })}` : ''} ·{' '}
          {t.rich('bar.repo', { ...rich, target })}
        </span>
        <button
          type="button"
          className="btn btn-primary"
          disabled={publish.isPending || total === 0}
          onClick={doPublish}
        >
          <Icon name={publish.isPending ? 'loader' : 'upload'} />
          {t('publish')}
        </button>
      </div>
    </div>
  )
}
