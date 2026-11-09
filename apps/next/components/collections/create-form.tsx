'use client'

import { type FormEvent, useState } from 'react'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'
import type { EmbeddingModelOut, HubView } from '@/api/types'
import { Icon } from '@/components/app/icon'
import { formatBytes, splitRepoId } from '@/components/hub/format'
import { useCreateCollection, useHubDataset, useHubDatasets, useHubRows } from '@/hooks'
import { cn } from '@/lib/utils'
import {
  defaultCollectionName,
  defaultColumns,
  isTrivialTest,
  modelGroups,
  modelLabel,
} from './format'

// The server refuses more (services/collections.py MAX_TEXT_COLUMNS).
const MAX_TEXT_COLUMNS = 4

const viewKey = (view: HubView) => `${view.config}\u0000${view.split}`

function viewLabel(view: HubView): string {
  const name = view.config === 'default' ? view.split : `${view.config} / ${view.split}`
  return view.num_bytes != null ? `${name} · ${formatBytes(view.num_bytes)}` : name
}

function modelOption(model: EmbeddingModelOut): string {
  const facts = [
    model.languages,
    model.dimensions ? `${model.dimensions} dimensions` : null,
    model.size_mb ? `${model.size_mb} MB` : null,
  ].filter(Boolean)
  return `${modelLabel(model.name)}${facts.length ? ` — ${facts.join(' · ')}` : ''}`
}

export function CreateCollectionForm({
  models,
  initialRepo,
  onCancel,
}: {
  models: EmbeddingModelOut[]
  initialRepo: string | null
  onCancel: () => void
}) {
  const router = useRouter()
  const create = useCreateCollection()
  const datasets = useHubDatasets()

  const [repoId, setRepoId] = useState(initialRepo ?? '')
  const repo = splitRepoId(repoId)
  const detail = useHubDataset(repo, null, repoId.includes('/'))
  const views = detail.data?.views ?? []
  const maxBytes = detail.data?.max_view_bytes ?? Number.POSITIVE_INFINITY
  const fits = (v: HubView) => v.num_bytes == null || v.num_bytes <= maxBytes

  const [pickedView, setPickedView] = useState<string | null>(null)
  const view = views.find((v) => viewKey(v) === pickedView) ?? views.find(fits) ?? null

  // One row is enough: the columns, their kinds and the detected Q/A columns.
  const rows = useHubRows(
    repo,
    { revision: detail.data?.sha, config: view?.config, split: view?.split, length: 1 },
    Boolean(view && detail.data),
  )
  const strings = (rows.data?.features ?? []).filter((f) => f.kind === 'string').map((f) => f.name)
  const columnsKey = view ? `${repoId}\u0000${viewKey(view)}` : ''
  const defaults = defaultColumns({ strings, qa: rows.data?.qa })
  // The user's picks hold for the split they were made on; another split
  // starts again from its own defaults.
  const [picked, setPicked] = useState<{
    key: string
    text: string[]
    query: string | null
  } | null>(null)
  const columns = picked?.key === columnsKey ? picked : { key: columnsKey, ...defaults }

  const [model, setModel] = useState(models[0]?.name ?? '')
  const chosenModel = models.find((m) => m.name === model) ?? models[0]
  const [name, setName] = useState<string | null>(null)
  const effectiveName = name ?? defaultCollectionName(repoId, view?.split ?? '', model)

  const toggle = (column: string, on: boolean) => {
    const text = on ? [...columns.text, column] : columns.text.filter((c) => c !== column)
    setPicked({ key: columnsKey, text, query: columns.query })
  }
  const setQuery = (query: string | null) =>
    setPicked({ key: columnsKey, text: columns.text, query })

  const valid =
    Boolean(view && detail.data && rows.data) &&
    columns.text.length > 0 &&
    effectiveName.trim() !== '' &&
    Boolean(model)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!valid || !view || !detail.data) return
    create.mutate(
      {
        name: effectiveName.trim(),
        repo_id: repoId,
        // What the form showed: the build reads the split at this commit.
        revision: detail.data.sha,
        config: view.config,
        split: view.split,
        text_columns: columns.text,
        query_column: columns.query,
        model,
      },
      {
        onSuccess: (collection) => {
          toast.success(`Building "${collection.name}"`)
          router.push(`/collections/${collection.id}`)
        },
        onError: (error) => toast.error(error.message),
      },
    )
  }

  const repoIds = datasets.data?.datasets.map((d) => d.id) ?? []
  if (initialRepo && !repoIds.includes(initialRepo)) repoIds.unshift(initialRepo)
  const trivial = isTrivialTest(columns.text, columns.query)

  return (
    <form className="card coll-form" onSubmit={submit}>
      <div className="card-head">
        <div>
          <div className="card-title">New collection</div>
          <p className="card-desc">
            One split of a dataset, read from Hugging Face at its latest commit and embedded row by
            row: with a local model on the server, no data leaves your stack; with your endpoint's
            embedding model, the rows are sent to it.
          </p>
        </div>
      </div>

      <div className="grid-2 coll-form-grid">
        <div className="field">
          <label className="label" htmlFor="coll-repo">
            Dataset
          </label>
          <select
            id="coll-repo"
            className="select mono"
            value={repoId}
            onChange={(e) => {
              setRepoId(e.target.value)
              setPickedView(null)
            }}
          >
            <option value="">{datasets.isPending ? 'Loading your datasets…' : 'Pick one'}</option>
            {repoIds.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
          {datasets.error && <div className="hint coll-error">{datasets.error.message}</div>}
        </div>

        <div className="field">
          <label className="label" htmlFor="coll-split">
            Split
          </label>
          <select
            id="coll-split"
            className="select"
            value={view ? viewKey(view) : ''}
            disabled={!views.length}
            onChange={(e) => setPickedView(e.target.value)}
          >
            {!views.length && (
              <option value="">{detail.isFetching ? 'Reading the dataset…' : '—'}</option>
            )}
            {views.map((v) => (
              <option key={viewKey(v)} value={viewKey(v)} disabled={!fits(v)}>
                {viewLabel(v)}
                {fits(v) ? '' : ' (too large)'}
              </option>
            ))}
          </select>
          {detail.error && <div className="hint coll-error">{detail.error.message}</div>}
        </div>
      </div>

      {view && (
        <fieldset className="coll-fieldset">
          <legend className="label">Text to embed</legend>
          {rows.isPending ? (
            <div className="hint">
              <Icon name="loader" className="animate-spin ic-sm" /> Reading the columns…
            </div>
          ) : rows.error ? (
            <div className="hint coll-error">{rows.error.message}</div>
          ) : strings.length === 0 ? (
            <div className="hint coll-error">This split has no text column to embed.</div>
          ) : (
            <div className="coll-chips">
              {strings.map((column) => {
                const on = columns.text.includes(column)
                const full = !on && columns.text.length >= MAX_TEXT_COLUMNS
                return (
                  <label key={column} className={cn('coll-chip', on && 'on', full && 'off')}>
                    <input
                      type="checkbox"
                      checked={on}
                      disabled={full}
                      onChange={(e) => toggle(column, e.target.checked)}
                    />
                    <span className="mono">{column}</span>
                  </label>
                )
              })}
            </div>
          )}
          <div className="hint">
            Joined in this order, a blank line between them. Rows empty in all of them are skipped.
          </div>
        </fieldset>
      )}

      {view && strings.length > 0 && (
        <div className="grid-2 coll-form-grid">
          <div className="field">
            <label className="label" htmlFor="coll-query">
              Questions for the retrieval test
            </label>
            <select
              id="coll-query"
              className="select mono"
              value={columns.query ?? ''}
              onChange={(e) => setQuery(e.target.value || null)}
            >
              <option value="">None</option>
              {strings.map((column) => (
                <option key={column} value={column}>
                  {column}
                </option>
              ))}
            </select>
            <div className={cn('hint', trivial && 'coll-warn')}>
              {trivial
                ? 'This column is embedded too, so every row finds itself: embed the answer only to test retrieval.'
                : 'Each tested row asks with this column; a hit is its own row coming back first.'}
            </div>
          </div>

          <div className="field">
            <label className="label" htmlFor="coll-model">
              Embedding model
            </label>
            <select
              id="coll-model"
              className="select"
              value={model}
              onChange={(e) => setModel(e.target.value)}
            >
              {modelGroups(models).map((group) => (
                <optgroup key={group.label} label={group.label}>
                  {group.models.map((m) => (
                    <option key={m.name} value={m.name}>
                      {modelOption(m)}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
            {chosenModel && <div className="hint">{chosenModel.description}</div>}
          </div>
        </div>
      )}

      {view && strings.length > 0 && (
        <div className="field">
          <label className="label" htmlFor="coll-name">
            Name
          </label>
          <input
            id="coll-name"
            className="input"
            maxLength={100}
            value={effectiveName}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
      )}

      <div className="coll-form-actions">
        <button type="submit" className="btn btn-primary" disabled={!valid || create.isPending}>
          <Icon name={create.isPending ? 'loader' : 'boxes'} />
          Build collection
        </button>
        <button type="button" className="btn btn-ghost" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  )
}
