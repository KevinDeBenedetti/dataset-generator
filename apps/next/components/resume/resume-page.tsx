'use client'

import { useLocale, useTranslations } from 'next-intl'
import { useState } from 'react'
import { errorStatus } from '@/api/sdk'
import type { ResumeSummary } from '@/api/types'
import { Icon } from '@/components/app/icon'
import { timeAgo } from '@/components/hub/format'
import { useResumes } from '@/hooks'
import { cn } from '@/lib/utils'
import { ResumeView } from './resume-view'

/** What the page says when it can't list the resumes. */
function ResumeProblem({ error }: { error: Error }) {
  const t = useTranslations('resume')
  const status = errorStatus(error)
  const title =
    status === 400
      ? t('problem.connectTitle')
      : status === 403
        ? t('problem.adminsTitle')
        : t('problem.readFailedTitle')
  const desc =
    status === 400
      ? t('problem.connectDescription')
      : status === 403
        ? t('problem.adminsDescription')
        : error.message
  return (
    <div className="card hub-empty">
      <span className="cell-ic ic-lg">
        <Icon name={status === 400 ? 'key' : 'alert'} className="ic-lg" />
      </span>
      <div>
        <div className="card-title">{title}</div>
        <p className="card-desc">{desc}</p>
      </div>
    </div>
  )
}

function ResumeList({
  resumes,
  instance,
  open,
  onOpen,
}: {
  resumes: ResumeSummary[]
  instance: string
  open: string | null
  onOpen: (id: string) => void
}) {
  const t = useTranslations('resume')
  const locale = useLocale()
  const [now] = useState(() => Date.now())
  return (
    <div className="card gh-repos">
      <div className="gh-repos-filters">
        <span className="hint">{t('list.count', { count: resumes.length, instance })}</span>
      </div>
      <ul className="gh-repo-list">
        {resumes.map((r) => (
          <li key={r.id} className={cn('gh-repo', open === r.id && 'is-open')}>
            <button
              type="button"
              className="gh-repo-main"
              aria-pressed={open === r.id}
              onClick={() => onOpen(r.id)}
            >
              <span className="gh-repo-name">
                {r.name}
                {r.is_public && <span className="tag">{t('list.public')}</span>}
                {r.is_locked && <span className="tag">{t('list.locked')}</span>}
              </span>
              <span className="gh-repo-desc mono">{r.slug}</span>
              <span className="gh-repo-meta">
                {(r.tags ?? []).map((tag) => (
                  <span key={tag}>#{tag}</span>
                ))}
                {r.updated_at && (
                  <span>{t('list.updated', { ago: timeAgo(r.updated_at, now, locale) })}</span>
                )}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function ResumePage() {
  const t = useTranslations('resume')
  const resumes = useResumes()
  const [openId, setOpenId] = useState<string | null>(null)
  const list = resumes.data?.resumes ?? []
  const open = list.find((r) => r.id === openId) ? openId : null

  return (
    <div className="hub-page gh-page">
      <div className="page-head">
        <div>
          <h1 className="page-title">{t('title')}</h1>
          <p className="page-sub">{t('subtitle')}</p>
        </div>
      </div>

      {resumes.error ? (
        <ResumeProblem error={resumes.error} />
      ) : !resumes.data ? (
        <div className="card hub-loading" aria-busy="true">
          <Icon name="loader" className="animate-spin" />
          {t('list.loading')}
        </div>
      ) : list.length === 0 ? (
        <div className="card hub-empty">
          <span className="cell-ic ic-lg">
            <Icon name="fileText" className="ic-lg" />
          </span>
          <div>
            <div className="card-title">{t('list.emptyTitle')}</div>
            <p className="card-desc">
              {t('list.emptyDescription', { instance: resumes.data.instance })}
            </p>
          </div>
        </div>
      ) : (
        <div className={open ? 'gh-layout has-panel' : 'gh-layout'}>
          <ResumeList
            resumes={list}
            instance={resumes.data.instance}
            open={open}
            onOpen={setOpenId}
          />
          {open && <ResumeView key={open} id={open} onClose={() => setOpenId(null)} />}
        </div>
      )}
    </div>
  )
}
