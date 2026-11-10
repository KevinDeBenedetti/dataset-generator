'use client'

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
  const status = errorStatus(error)
  const title =
    status === 400
      ? 'Connect Reactive Resume'
      : status === 403
        ? 'Admins only'
        : "Couldn't read Reactive Resume"
  const desc =
    status === 400
      ? 'Set REACTIVE_RESUME_API_KEY on the server, and REACTIVE_RESUME_URL for a self-hosted instance (blank: rxresu.me), then reload this page.'
      : status === 403
        ? 'The resumes are read with the server’s own Reactive Resume key: only an admin sees them.'
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
  const [now] = useState(() => Date.now())
  return (
    <div className="card gh-repos">
      <div className="gh-repos-filters">
        <span className="hint">
          {resumes.length} on {instance}
        </span>
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
                {r.is_public && <span className="tag">public</span>}
                {r.is_locked && <span className="tag">locked</span>}
              </span>
              <span className="gh-repo-desc mono">{r.slug}</span>
              <span className="gh-repo-meta">
                {(r.tags ?? []).map((tag) => (
                  <span key={tag}>#{tag}</span>
                ))}
                {r.updated_at && <span>updated {timeAgo(r.updated_at, now)}</span>}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function ResumePage() {
  const resumes = useResumes()
  const [openId, setOpenId] = useState<string | null>(null)
  const list = resumes.data?.resumes ?? []
  const open = list.find((r) => r.id === openId) ? openId : null

  return (
    <div className="hub-page gh-page">
      <div className="page-head">
        <div>
          <h1 className="page-title">Resume</h1>
          <p className="page-sub">
            Your resumes on Reactive Resume, read with the server&apos;s API key. Pick one to read
            it as text: its sections and descriptions, hidden ones left out.
          </p>
        </div>
      </div>

      {resumes.error ? (
        <ResumeProblem error={resumes.error} />
      ) : !resumes.data ? (
        <div className="card hub-loading" aria-busy="true">
          <Icon name="loader" className="animate-spin" />
          Listing your resumes…
        </div>
      ) : list.length === 0 ? (
        <div className="card hub-empty">
          <span className="cell-ic ic-lg">
            <Icon name="fileText" className="ic-lg" />
          </span>
          <div>
            <div className="card-title">No resume yet</div>
            <p className="card-desc">
              The API key&apos;s account on {resumes.data.instance} holds no resume.
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
