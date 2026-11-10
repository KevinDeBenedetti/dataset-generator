'use client'

import Link from 'next/link'
import { type FormEvent, useState } from 'react'
import { toast } from 'sonner'
import type { JobRunOut, RecipeIn, RecipeOut } from '@/api/types'
import { Icon } from '@/components/app/icon'
import { ModelSelect } from '@/components/app/model-select'
import { datasetHref } from '@/components/hub/format'
import { useCancelJobRun, useCreateRecipe, useDeleteRecipe, useJobRun, useRunRecipe } from '@/hooks'
import { HF_REPO_PATTERN, defaultTargetRepo, selectsSomething } from './recipe-state'

/** Create a recipe: a name, and the Hugging Face repo it publishes to. */
export function NewRecipeForm({
  namespace,
  onCreated,
  onCancel,
}: {
  namespace: string | null
  onCreated: (recipe: RecipeOut) => void
  onCancel?: () => void
}) {
  const [name, setName] = useState('')
  const [target, setTarget] = useState<string | null>(null)
  const create = useCreateRecipe()
  const targetRepo = target ?? defaultTargetRepo(name || 'github-qa', namespace)
  const valid = name.trim() !== '' && HF_REPO_PATTERN.test(targetRepo)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!valid) return
    create.mutate(
      { name: name.trim(), target_repo: targetRepo, include_profile: true, sources: [] },
      {
        onSuccess: (recipe) => {
          toast.success(`Recipe "${recipe.name}" created`)
          onCreated(recipe)
        },
        onError: (error) => toast.error(error.message),
      },
    )
  }

  return (
    <form className="gh-new-recipe" onSubmit={submit}>
      <div className="field">
        <label className="label" htmlFor="recipe-name">
          Recipe name
        </label>
        <input
          id="recipe-name"
          className="input"
          placeholder="Portfolio Q&A"
          maxLength={100}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>
      <div className="field">
        <label className="label" htmlFor="recipe-target">
          Hugging Face dataset
        </label>
        <input
          id="recipe-target"
          className="input mono"
          value={targetRepo}
          onChange={(e) => setTarget(e.target.value)}
          aria-invalid={!HF_REPO_PATTERN.test(targetRepo)}
        />
        <div className="hint">Created private on the first publish.</div>
      </div>
      <div className="gh-new-actions">
        <button type="submit" className="btn btn-primary" disabled={!valid || create.isPending}>
          <Icon name={create.isPending ? 'loader' : 'plus'} />
          Create recipe
        </button>
        {onCancel && (
          <button type="button" className="btn btn-ghost" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
    </form>
  )
}

function RunStatus({ run, recipe }: { run: JobRunOut; recipe: RecipeIn }) {
  const cancel = useCancelJobRun(run.id)
  if (run.status === 'queued' || run.status === 'running') {
    const { done = 0, total = 0, label = '' } = run.progress ?? {}
    const pct = total > 0 ? Math.round((done / total) * 100) : 4
    return (
      <div className="gh-run">
        <div className="hint">
          {run.status === 'queued'
            ? 'Queued — waiting for a worker.'
            : total > 0
              ? `Generating… ${done}/${total} repos${label ? ` · ${label}` : ''}`
              : label || 'Reading GitHub…'}
        </div>
        <div className="job-progress">
          <div style={{ width: `${pct}%` }} />
        </div>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={() => cancel.mutate()}
          disabled={cancel.isPending || !!run.cancel_requested}
        >
          {run.cancel_requested ? 'Cancelling…' : 'Cancel'}
        </button>
      </div>
    )
  }
  if (run.status === 'publishing') {
    return <div className="gh-run hint">Publishing to Hugging Face…</div>
  }
  if (run.status === 'published') {
    return (
      <div className="gh-run hint">
        Published {run.published_at ? new Date(run.published_at).toLocaleString() : ''} ·{' '}
        <Link href={datasetHref(recipe.target_repo)}>Open the dataset</Link>
      </div>
    )
  }
  if (run.status === 'succeeded' && run.preview) {
    const preview = run.preview
    return (
      <div className="gh-run">
        <div className="gh-run-counts">
          <span>
            <b>{preview.new.length}</b> new
          </span>
          <span>
            <b>{preview.kept}</b> kept
          </span>
          {preview.review.length > 0 && (
            <span>
              <b>{preview.review.length}</b> held out
            </span>
          )}
          {(preview.removed ?? []).length > 0 && (
            <span>
              <b>{preview.removed?.length}</b> removed
            </span>
          )}
        </div>
        <div className="gh-run-review">
          <span className="hint">Draft ready: review it before it goes to Hugging Face.</span>
          <Link className="btn btn-primary btn-sm" href={`/drafts/runs/${run.id}`}>
            <Icon name="eye" />
            Review the draft
          </Link>
        </div>
      </div>
    )
  }
  return (
    <div className="gh-run hint job-error">
      {run.status === 'cancelled'
        ? 'The last generation was cancelled.'
        : run.status === 'interrupted'
          ? 'The last generation was interrupted (its worker stopped). Generate again.'
          : `The last generation failed: ${run.error ?? 'unknown error'}`}
    </div>
  )
}

/** The recipe being edited: which one, where it publishes, and Generate. */
export function RecipeBar({
  recipes,
  current,
  working,
  saving,
  dirty,
  namespace,
  onSelect,
  onChange,
}: {
  recipes: RecipeOut[]
  current: RecipeOut
  working: RecipeIn
  saving: boolean
  dirty: boolean
  namespace: string | null
  onSelect: (id: string | null) => void
  onChange: (recipe: RecipeIn) => void
}) {
  const [creating, setCreating] = useState(false)
  const [target, setTarget] = useState<string | null>(null)
  const run = useJobRun(current.latest_run?.id)
  const start = useRunRecipe()
  const remove = useDeleteRecipe()
  const active = ['queued', 'running', 'publishing'].includes(run.data?.status ?? '')
  const sources = working.sources ?? []
  const nothing = !selectsSomething(working)
  const targetValue = target ?? working.target_repo
  const targetValid = HF_REPO_PATTERN.test(targetValue)

  const generate = () =>
    start.mutate(
      { id: current.id },
      {
        onSuccess: () => toast.success('Generation queued: it runs on the server.'),
        onError: (error) => toast.error(error.message),
      },
    )

  const destroy = () => {
    if (!window.confirm(`Delete the recipe "${current.name}"? Its Hugging Face dataset stays.`)) {
      return
    }
    remove.mutate(current.id, {
      onSuccess: () => onSelect(null),
      onError: (error) => toast.error(error.message),
    })
  }

  if (creating) {
    return (
      <div className="card gh-recipe">
        <div className="card-title">New recipe</div>
        <NewRecipeForm
          namespace={namespace}
          onCancel={() => setCreating(false)}
          onCreated={(recipe) => {
            setCreating(false)
            onSelect(recipe.id)
          }}
        />
      </div>
    )
  }

  return (
    <div className="card gh-recipe">
      <div className="gh-recipe-row">
        <div className="field gh-recipe-pick">
          <label className="label" htmlFor="recipe-pick">
            Recipe
          </label>
          <div className="gh-inline">
            <select
              id="recipe-pick"
              className="select"
              value={current.id}
              onChange={(e) => onSelect(e.target.value)}
            >
              {recipes.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
            <button type="button" className="btn btn-outline" onClick={() => setCreating(true)}>
              <Icon name="plus" />
              New
            </button>
          </div>
        </div>
        <div className="field gh-recipe-target">
          <label className="label" htmlFor="recipe-target-edit">
            Publishes to
          </label>
          <input
            id="recipe-target-edit"
            className="input mono"
            value={targetValue}
            aria-invalid={!targetValid}
            onChange={(e) => setTarget(e.target.value)}
            onBlur={() => {
              if (targetValid && targetValue !== working.target_repo) {
                onChange({ ...working, target_repo: targetValue })
              }
              setTarget(null)
            }}
          />
        </div>
        <div className="field">
          <label className="label" htmlFor="recipe-model">
            Model
          </label>
          <ModelSelect
            id="recipe-model"
            className="select"
            value={working.model_ref ?? ''}
            onChange={(ref) => onChange({ ...working, model_ref: ref || null })}
          />
        </div>
      </div>

      <div className="gh-recipe-row gh-recipe-foot">
        <label className="gh-toggle">
          <input
            type="checkbox"
            checked={working.include_profile ?? true}
            onChange={(e) => onChange({ ...working, include_profile: e.target.checked })}
          />
          Profile facts (who you are, your stack, your projects)
        </label>
        <span className="hint">
          {sources.length} repo{sources.length === 1 ? '' : 's'} selected ·{' '}
          {saving ? 'Saving…' : dirty ? 'Unsaved changes' : 'Saved'}
        </span>
        <div className="gh-recipe-actions">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={destroy}
            disabled={remove.isPending}
          >
            <Icon name="trash" />
            Delete
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={generate}
            disabled={active || start.isPending || saving || dirty || nothing}
            title={nothing ? 'Select a repo or the profile facts first' : undefined}
          >
            <Icon name={start.isPending ? 'loader' : 'sparkles'} />
            Generate draft
          </button>
        </div>
      </div>

      {run.data && <RunStatus run={run.data} recipe={working} />}
    </div>
  )
}
