'use client'

import Link from 'next/link'
import { type FormEvent, useState } from 'react'
import { useLocale, useTranslations } from 'next-intl'
import { toast } from 'sonner'
import type { JobRunOut, RecipeIn, RecipeOut } from '@/api/types'
import { Icon } from '@/components/app/icon'
import { ModelSelect } from '@/components/app/model-select'
import { datasetHref } from '@/components/hub/format'
import {
  useCancelJobRun,
  useCreateRecipe,
  useDeleteRecipe,
  useJobRun,
  useRecipeSchedule,
  useRunRecipe,
  useSaveRecipeSchedule,
} from '@/hooks'
import { rich, richLink } from '@/lib/rich'
import { SchedulePicker } from '@/components/jobs/schedule-picker'
import { type ScheduleForm, scheduleForm, toSchedule } from '@/components/jobs/schedule-state'
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
  const t = useTranslations('github')
  const tc = useTranslations('common')
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
          toast.success(t('recipe.created', { name: recipe.name }))
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
          {t('recipe.name')}
        </label>
        <input
          id="recipe-name"
          className="input"
          placeholder={t('recipe.namePlaceholder')}
          maxLength={100}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>
      <div className="field">
        <label className="label" htmlFor="recipe-target">
          {t('recipe.dataset')}
        </label>
        <input
          id="recipe-target"
          className="input mono"
          value={targetRepo}
          onChange={(e) => setTarget(e.target.value)}
          aria-invalid={!HF_REPO_PATTERN.test(targetRepo)}
        />
        <div className="hint">{t('recipe.datasetHint')}</div>
      </div>
      <div className="gh-new-actions">
        <button type="submit" className="btn btn-primary" disabled={!valid || create.isPending}>
          <Icon name={create.isPending ? 'loader' : 'plus'} />
          {t('recipe.create')}
        </button>
        {onCancel && (
          <button type="button" className="btn btn-ghost" onClick={onCancel}>
            {tc('cancel')}
          </button>
        )}
      </div>
    </form>
  )
}

function RunStatus({ run, recipe }: { run: JobRunOut; recipe: RecipeIn }) {
  const t = useTranslations('github')
  const tc = useTranslations('common')
  const locale = useLocale()
  const cancel = useCancelJobRun(run.id)
  if (run.status === 'queued' || run.status === 'running') {
    const { done = 0, total = 0, label = '' } = run.progress ?? {}
    const pct = total > 0 ? Math.round((done / total) * 100) : 4
    return (
      <div className="gh-run">
        <div className="hint">
          {run.status === 'queued'
            ? t('run.queued')
            : total > 0
              ? label
                ? t('run.generatingLabel', { done, total, label })
                : t('run.generating', { done, total })
              : label || t('run.reading')}
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
          {run.cancel_requested ? t('run.cancelling') : tc('cancel')}
        </button>
      </div>
    )
  }
  if (run.status === 'publishing') {
    return <div className="gh-run hint">{t('run.publishing')}</div>
  }
  if (run.status === 'published') {
    const link = richLink(datasetHref(recipe.target_repo))
    return (
      <div className="gh-run hint">
        {run.published_at
          ? t.rich('run.published', {
              date: new Date(run.published_at).toLocaleString(locale),
              link,
            })
          : t.rich('run.publishedUndated', { link })}
      </div>
    )
  }
  if (run.status === 'succeeded' && run.preview) {
    const preview = run.preview
    return (
      <div className="gh-run">
        <div className="gh-run-counts">
          <span>{t.rich('run.new', { count: preview.new.length, b: rich.b })}</span>
          <span>{t.rich('run.kept', { count: preview.kept, b: rich.b })}</span>
          {preview.review.length > 0 && (
            <span>{t.rich('run.heldOut', { count: preview.review.length, b: rich.b })}</span>
          )}
          {(preview.removed ?? []).length > 0 && (
            <span>{t.rich('run.removed', { count: preview.removed?.length ?? 0, b: rich.b })}</span>
          )}
        </div>
        <div className="gh-run-review">
          <span className="hint">{t('run.draftReady')}</span>
          <Link className="btn btn-primary btn-sm" href={`/drafts/runs/${run.id}`}>
            <Icon name="eye" />
            {t('run.reviewDraft')}
          </Link>
        </div>
      </div>
    )
  }
  return (
    <div className="gh-run hint job-error">
      {run.status === 'cancelled'
        ? t('run.cancelled')
        : run.status === 'interrupted'
          ? t('run.interrupted')
          : t('run.failed', { error: run.error ?? t('run.unknownError') })}
    </div>
  )
}

/** When the recipe's dataset regenerates by itself. Saved on every change,
 * like the recipe; "Only when I start it" removes the schedule. */
function RecipeSchedule({ recipeId }: { recipeId: string }) {
  const t = useTranslations('github')
  const locale = useLocale()
  const saved = useRecipeSchedule(recipeId)
  const save = useSaveRecipeSchedule(recipeId)
  const form = scheduleForm(saved.data)

  if (saved.isPending) return null
  return (
    <SchedulePicker
      id="recipe-every"
      form={form}
      disabled={save.isPending}
      publishLabel={t('schedule.publishLabel')}
      skipped={saved.data?.skipped}
      onChange={(patch: Partial<ScheduleForm>) =>
        save.mutate(toSchedule({ ...form, ...patch }), {
          onError: (error) => toast.error(error.message),
        })
      }
    >
      {t('schedule.description', { time: form.time })}
      {saved.data?.next_run_at &&
        ` ${t('schedule.nextRun', {
          date: new Date(saved.data.next_run_at).toLocaleString(locale),
        })}`}
    </SchedulePicker>
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
  const t = useTranslations('github')
  const tc = useTranslations('common')
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
        onSuccess: () => toast.success(t('recipe.generationQueued')),
        onError: (error) => toast.error(error.message),
      },
    )

  const destroy = () => {
    if (!window.confirm(t('recipe.confirmDelete', { name: current.name }))) {
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
        <div className="card-title">{t('recipe.newTitle')}</div>
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
            {t('recipe.label')}
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
              {t('recipe.new')}
            </button>
          </div>
        </div>
        <div className="field gh-recipe-target">
          <label className="label" htmlFor="recipe-target-edit">
            {t('recipe.publishesTo')}
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
            {t('recipe.model')}
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
          {t('recipe.profileFacts')}
        </label>
        <span className="hint">
          {t('recipe.reposSelected', { count: sources.length })} ·{' '}
          {saving ? t('recipe.saving') : dirty ? t('recipe.unsaved') : t('recipe.saved')}
        </span>
        <div className="gh-recipe-actions">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={destroy}
            disabled={remove.isPending}
          >
            <Icon name="trash" />
            {tc('delete')}
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={generate}
            disabled={active || start.isPending || saving || dirty || nothing}
            title={nothing ? t('recipe.nothingSelected') : undefined}
          >
            <Icon name={start.isPending ? 'loader' : 'sparkles'} />
            {t('recipe.generate')}
          </button>
        </div>
      </div>

      <RecipeSchedule key={current.id} recipeId={current.id} />

      {run.data && <RunStatus run={run.data} recipe={working} />}
    </div>
  )
}
