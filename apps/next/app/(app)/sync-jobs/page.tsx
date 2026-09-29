'use client'

import { useState } from 'react'
import './sync-jobs.css'
import { Icon } from '@/components/app/icon'
import { useJobsStatus, useTriggerCorpusSync, useTriggerQADatasetSync } from '@/hooks'
import { useIsAdmin } from '@/hooks/use-auth'
import type {
  CorpusJobStatus,
  CorpusSource,
  CorpusSyncResponse,
  QADatasetJobStatus,
  QADatasetSyncResponse,
} from '@/api/sdk'

const CORPUS_SOURCES: { id: CorpusSource; label: string; hint: string }[] = [
  { id: 'profile', label: 'Profile', hint: 'Bio, derived skills, one chunk per project' },
  { id: 'github', label: 'GitHub', hint: 'Profile overview + one chunk per repository' },
  { id: 'github_code', label: 'Code', hint: 'Source files, chunked per function/class' },
  { id: 'github_docs', label: 'Docs', hint: 'docs/ folders, chunked per heading' },
]

function Switch({
  on,
  onToggle,
  label,
  disabled,
}: {
  on: boolean
  onToggle: () => void
  label: string
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      className={`switch${on ? ' on' : ''}`}
      role="switch"
      aria-checked={on}
      aria-label={label}
      disabled={disabled}
      onClick={onToggle}
    />
  )
}

function ConfigHint({ missing }: { missing: { label: string; ok: boolean }[] }) {
  const unset = missing.filter((m) => !m.ok)
  if (unset.length === 0) return null
  return (
    <p className="hint sync-config-hint">
      Server not configured — missing {unset.map((m) => m.label).join(', ')}.
    </p>
  )
}

function RunError({ error }: { error: unknown }) {
  if (!error) return null
  return (
    <p className="hint sync-error">{error instanceof Error ? error.message : 'The job failed'}</p>
  )
}

function CorpusJobCard({
  status,
  isAdmin,
}: {
  status: CorpusJobStatus | undefined
  isAdmin: boolean
}) {
  const [sources, setSources] = useState<Set<CorpusSource>>(
    new Set(CORPUS_SOURCES.map((s) => s.id)),
  )
  const [dryRun, setDryRun] = useState(true)
  const mutation = useTriggerCorpusSync()
  const result = mutation.data as CorpusSyncResponse | undefined

  const toggleSource = (id: CorpusSource) => {
    setSources((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const canRun = isAdmin && sources.size > 0 && !mutation.isPending
  const configured = status?.configured ?? false

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <div className="card-title">Portfolio knowledge corpus</div>
          <div className="card-desc">
            Weekly on Mondays 04:00 UTC via <code className="mono">dataset-sync.yml</code>
          </div>
        </div>
        <span className={`badge badge-${configured ? 'success' : 'destructive'}`}>
          <span className="dot" />
          {configured ? 'Configured' : 'Not configured'}
        </span>
      </div>
      <div
        className="card-body"
        style={{ paddingTop: 0, display: 'flex', flexDirection: 'column', gap: 14 }}
      >
        {status && (
          <ConfigHint
            missing={[
              { label: 'GITHUB_USERNAME', ok: status.github_username },
              { label: 'HF_TOKEN', ok: status.hf_token },
              { label: 'HF_DATASET_REPO', ok: status.hf_dataset_repo },
            ]}
          />
        )}

        <div>
          <div className="label" style={{ marginBottom: 8 }}>
            Splits to build
          </div>
          <div className="sync-source-list">
            {CORPUS_SOURCES.map((s) => (
              <div key={s.id} className="sync-source-row">
                <div>
                  <div className="label">{s.label}</div>
                  <div className="hint">{s.hint}</div>
                </div>
                <Switch
                  on={sources.has(s.id)}
                  onToggle={() => toggleSource(s.id)}
                  label={s.label}
                  disabled={mutation.isPending}
                />
              </div>
            ))}
          </div>
        </div>

        <div className="sync-source-row">
          <div>
            <div className="label">Dry run</div>
            <div className="hint">Build the corpus but skip publishing to Hugging Face</div>
          </div>
          <Switch
            on={dryRun}
            onToggle={() => setDryRun((v) => !v)}
            label="Dry run"
            disabled={mutation.isPending}
          />
        </div>
      </div>
      <div
        className="card-foot"
        style={{ flexDirection: 'column', alignItems: 'stretch', gap: 10 }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <button
            className="btn btn-primary"
            disabled={!canRun}
            onClick={() => mutation.mutate({ sources: [...sources], dryRun })}
          >
            <Icon
              name={mutation.isPending ? 'loader' : 'play'}
              className={mutation.isPending ? 'animate-spin' : undefined}
            />
            {mutation.isPending ? 'Running…' : dryRun ? 'Run (dry run)' : 'Run & publish'}
          </button>
          {!isAdmin && <span className="hint">Only an admin can run this job.</span>}
        </div>
        <RunError error={mutation.error} />
        {result && (
          <div className="sync-result">
            <div className="hint" style={{ marginBottom: 6 }}>
              {result.dry_run ? 'Dry run complete — nothing published.' : 'Published.'}{' '}
              {result.url && (
                <a href={result.url} target="_blank" rel="noopener noreferrer">
                  View on Hugging Face
                  <Icon name="external" className="ic-sm" />
                </a>
              )}
            </div>
            <table className="table">
              <thead>
                <tr>
                  <th>Split</th>
                  <th>Records</th>
                </tr>
              </thead>
              <tbody>
                {result.manifest.files.map((f) => (
                  <tr key={f.path}>
                    <td className="mono">{f.source}</td>
                    <td className="mono">{f.records}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

function QADatasetJobCard({
  status,
  isAdmin,
}: {
  status: QADatasetJobStatus | undefined
  isAdmin: boolean
}) {
  const [maxRepos, setMaxRepos] = useState('2')
  const [dryRun, setDryRun] = useState(true)
  const mutation = useTriggerQADatasetSync()
  const result = mutation.data as QADatasetSyncResponse | undefined

  const parsedMaxRepos = maxRepos.trim() ? Math.max(1, Math.round(Number(maxRepos))) : undefined
  const canRun = isAdmin && !mutation.isPending && (maxRepos.trim() === '' || parsedMaxRepos! >= 1)
  const configured = status?.configured ?? false

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <div className="card-title">GitHub Q&amp;A dataset</div>
          <div className="card-desc">
            Weekly on Mondays 06:00 UTC via <code className="mono">qa-dataset-sync.yml</code>
          </div>
        </div>
        <span className={`badge badge-${configured ? 'success' : 'destructive'}`}>
          <span className="dot" />
          {configured ? 'Configured' : 'Not configured'}
        </span>
      </div>
      <div
        className="card-body"
        style={{ paddingTop: 0, display: 'flex', flexDirection: 'column', gap: 14 }}
      >
        {status && (
          <ConfigHint
            missing={[
              { label: 'GITHUB_USERNAME', ok: status.github_username },
              {
                label: 'CLAUDE_CODE_OAUTH_TOKEN (or ANTHROPIC_API_KEY)',
                ok: status.claude_credentials,
              },
              { label: 'HF_TOKEN', ok: status.hf_token },
              { label: 'HF_QA_DATASET_REPO', ok: status.hf_qa_dataset_repo },
            ]}
          />
        )}

        <p className="hint">
          Generates via the Claude Agent SDK — billed against the configured Claude subscription
          even on a dry run. Cap the repo count for a cheap test.
        </p>

        <div className="field">
          <label htmlFor="qa-max-repos" className="label">
            Max repositories
          </label>
          <input
            id="qa-max-repos"
            className="input"
            type="number"
            min={1}
            placeholder="15 (default)"
            value={maxRepos}
            onChange={(e) => setMaxRepos(e.target.value)}
            disabled={mutation.isPending}
          />
        </div>

        <div className="sync-source-row">
          <div>
            <div className="label">Dry run</div>
            <div className="hint">Generate pairs but skip publishing to Hugging Face</div>
          </div>
          <Switch
            on={dryRun}
            onToggle={() => setDryRun((v) => !v)}
            label="Dry run"
            disabled={mutation.isPending}
          />
        </div>
      </div>
      <div
        className="card-foot"
        style={{ flexDirection: 'column', alignItems: 'stretch', gap: 10 }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <button
            className="btn btn-primary"
            disabled={!canRun}
            onClick={() => mutation.mutate({ maxRepos: parsedMaxRepos, dryRun })}
          >
            <Icon
              name={mutation.isPending ? 'loader' : 'play'}
              className={mutation.isPending ? 'animate-spin' : undefined}
            />
            {mutation.isPending ? 'Running…' : dryRun ? 'Run (dry run)' : 'Run & publish'}
          </button>
          {!isAdmin && <span className="hint">Only an admin can run this job.</span>}
        </div>
        <RunError error={mutation.error} />
        {result && (
          <div className="sync-result">
            <div className="hint" style={{ marginBottom: 6 }}>
              {result.dry_run ? 'Dry run complete — nothing published.' : 'Published.'}{' '}
              {result.url && (
                <a href={result.url} target="_blank" rel="noopener noreferrer">
                  View on Hugging Face
                  <Icon name="external" className="ic-sm" />
                </a>
              )}
            </div>
            <div style={{ display: 'flex', gap: 18, fontSize: 13 }}>
              <span>
                <strong>{result.records}</strong> pairs
              </span>
              <span className="muted">{result.dropped} dropped</span>
            </div>
            {result.errors.length > 0 && (
              <ul className="sync-error-list">
                {result.errors.map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export default function SyncJobsPage() {
  const statusQuery = useJobsStatus()
  const isAdmin = useIsAdmin()

  return (
    <div className="sync-jobs-page">
      <div className="page-head">
        <div>
          <h1 className="page-title">Sync jobs</h1>
          <p className="page-sub">
            Trigger the scheduled GitHub → Hugging Face jobs on demand — the same code the weekly
            GitHub Actions cron runs — without waiting for Monday.
          </p>
        </div>
        <div className="page-actions">
          <button
            className="btn btn-outline"
            onClick={() => statusQuery.refetch()}
            disabled={statusQuery.isRefetching}
            type="button"
          >
            <Icon
              name="refresh"
              className={statusQuery.isRefetching ? 'animate-spin' : undefined}
            />
            Refresh status
          </button>
        </div>
      </div>

      {statusQuery.error && (
        <p className="hint sync-error" style={{ marginBottom: 18 }}>
          {statusQuery.error instanceof Error
            ? statusQuery.error.message
            : 'Failed to load jobs status'}
        </p>
      )}

      <div className="grid-2" style={{ alignItems: 'start', gap: 24 }}>
        <CorpusJobCard status={statusQuery.data?.corpus} isAdmin={isAdmin} />
        <QADatasetJobCard status={statusQuery.data?.qa_dataset} isAdmin={isAdmin} />
      </div>
    </div>
  )
}
