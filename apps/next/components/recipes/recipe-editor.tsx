'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'
import type { RecipeStep, SchemaColumn, SourceRecipe } from '@/api/sdk'
import { Icon } from '@/components/app/icon'
import {
  useRecipe,
  useRecipePreview,
  useRunRecipe,
  useSaveSourceRecipeSchedule,
  useSourceRecipeSchedule,
  useUpdateRecipe,
} from '@/hooks/use-data-sources'
import { useJobRun } from '@/hooks/use-jobs'
import { SchedulePicker } from '@/components/jobs/schedule-picker'
import { type ScheduleForm, scheduleForm, toSchedule } from '@/components/jobs/schedule-state'
import {
  CAST_TARGETS,
  FILTER_OPERATORS,
  MASK_METHODS,
  STEP_OPS,
  columnsBefore,
  corpusOptions,
  filterValue,
  moveStep,
  newStep,
  removeStep,
  replaceStep,
  type StepOp,
} from './recipe-state'

const PREVIEW_DELAY_MS = 600
// The template syntax and examples (not translated: they are code).
const TEMPLATE_SYNTAX =
  '{column}, {column|number} (1 284), {column|decimal} (1 284,5), {column|date_fr} (2 janvier 2026), {column|lower|upper|title}; {{ }} for braces'
const QUESTION_EXAMPLE = 'Quelle est la population de {nom} ?'
const ANSWER_EXAMPLE = '{nom} compte {population|number} habitants.'

interface FactTemplateForm {
  question: string
  answer: string
  category: string
}

function ColumnSelect({
  value,
  columns,
  onChange,
  label,
}: {
  value: string
  columns: SchemaColumn[]
  onChange: (value: string) => void
  label: string
}) {
  const names = columns.map((c) => c.name)
  return (
    <select
      className="input"
      aria-label={label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      {!names.includes(value) && <option value={value}>{value || '—'}</option>}
      {names.map((n) => (
        <option key={n} value={n}>
          {n}
        </option>
      ))}
    </select>
  )
}

function ColumnChecks({
  value,
  columns,
  onChange,
}: {
  value: string[]
  columns: SchemaColumn[]
  onChange: (value: string[]) => void
}) {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
      {columns.map((c) => (
        <label key={c.name} className="hint" style={{ display: 'flex', gap: 4 }}>
          <input
            type="checkbox"
            checked={value.includes(c.name)}
            onChange={(e) =>
              onChange(e.target.checked ? [...value, c.name] : value.filter((v) => v !== c.name))
            }
          />
          <span className="mono">{c.name}</span>
        </label>
      ))}
    </div>
  )
}

function StepFields({
  step,
  columns,
  onChange,
}: {
  step: RecipeStep
  columns: SchemaColumn[]
  onChange: (step: RecipeStep) => void
}) {
  const t = useTranslations('recipes.step')
  const set = (patch: Record<string, unknown>) => onChange({ ...step, ...patch })
  const column = String(step.column ?? '')
  switch (step.op) {
    case 'select':
    case 'dedup':
    case 'trim':
      return (
        <>
          <ColumnChecks
            value={(step.columns as string[]) ?? []}
            columns={columns}
            onChange={(cols) => set({ columns: cols })}
          />
          {step.op === 'dedup' && (
            <select
              className="input"
              aria-label={t('keep')}
              value={String(step.keep ?? 'first')}
              onChange={(e) => set({ keep: e.target.value })}
            >
              <option value="first">{t('keepFirst')}</option>
              <option value="last">{t('keepLast')}</option>
            </select>
          )}
        </>
      )
    case 'rename': {
      const mapping = (step.mapping as Record<string, string>) ?? {}
      const [from, to] = Object.entries(mapping)[0] ?? ['', '']
      return (
        <div style={{ display: 'flex', gap: 6 }}>
          <ColumnSelect
            label={t('column')}
            value={from}
            columns={columns}
            onChange={(v) => set({ mapping: { [v]: to || v } })}
          />
          <input
            className="input"
            aria-label={t('newName')}
            value={to}
            onChange={(e) => set({ mapping: { [from]: e.target.value } })}
          />
        </div>
      )
    }
    case 'cast':
      return (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <ColumnSelect
            label={t('column')}
            value={column}
            columns={columns}
            onChange={(v) => set({ column: v })}
          />
          <select
            className="input"
            aria-label={t('to')}
            value={String(step.to)}
            onChange={(e) => set({ to: e.target.value })}
          >
            {CAST_TARGETS.map((target) => (
              <option key={target} value={target}>
                {t(`types.${target}`)}
              </option>
            ))}
          </select>
          {(step.to === 'date' || step.to === 'timestamp') && (
            <input
              className="input mono"
              aria-label={t('format')}
              placeholder="%d/%m/%Y"
              value={String(step.format ?? '')}
              onChange={(e) => set({ format: e.target.value || undefined })}
            />
          )}
          {(step.to === 'integer' || step.to === 'double') && (
            <label className="hint" style={{ display: 'flex', gap: 4 }}>
              <input
                type="checkbox"
                checked={Boolean(step.decimal_comma)}
                onChange={(e) => set({ decimal_comma: e.target.checked })}
              />
              {t('decimalComma')}
            </label>
          )}
        </div>
      )
    case 'filter': {
      const operator = String(step.operator)
      const shown = Array.isArray(step.value)
        ? (step.value as unknown[]).join(', ')
        : String(step.value ?? '')
      return (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <ColumnSelect
            label={t('column')}
            value={column}
            columns={columns}
            onChange={(v) => set({ column: v })}
          />
          <select
            className="input"
            aria-label={t('operator')}
            value={operator}
            onChange={(e) =>
              set({
                operator: e.target.value,
                value: filterValue(e.target.value, shown),
              })
            }
          >
            {FILTER_OPERATORS.map((op) => (
              <option key={op} value={op}>
                {t(`operators.${op}`)}
              </option>
            ))}
          </select>
          {operator !== 'is_null' && operator !== 'not_null' && (
            <input
              className="input"
              aria-label={t('value')}
              defaultValue={shown}
              onChange={(e) => set({ value: filterValue(operator, e.target.value) })}
            />
          )}
        </div>
      )
    }
    case 'mask':
      return (
        <div style={{ display: 'flex', gap: 6 }}>
          <ColumnSelect
            label={t('column')}
            value={column}
            columns={columns}
            onChange={(v) => set({ column: v })}
          />
          <select
            className="input"
            aria-label={t('method')}
            value={String(step.method)}
            onChange={(e) => set({ method: e.target.value })}
          >
            {MASK_METHODS.map((m) => (
              <option key={m} value={m}>
                {t(`methods.${m}`)}
              </option>
            ))}
          </select>
        </div>
      )
    case 'limit':
      return (
        <input
          className="input"
          type="number"
          min={0}
          aria-label={t('rows')}
          value={Number(step.rows ?? 0)}
          onChange={(e) => set({ rows: Math.max(0, Number(e.target.value) || 0) })}
        />
      )
    default:
      return null
  }
}

// When the recipe refreshes by itself (#314): an unchanged data source starts
// no run; a changed one runs and, when "publish" is on, publishes what passes.
function RecipeSchedule({ recipeId }: { recipeId: string }) {
  const t = useTranslations('recipes')
  const saved = useSourceRecipeSchedule(recipeId)
  const save = useSaveSourceRecipeSchedule(recipeId)
  const form = scheduleForm(saved.data)
  if (saved.isPending) return null
  return (
    <SchedulePicker
      id={`recipe-every-${recipeId}`}
      form={form}
      disabled={save.isPending}
      publishLabel={t('schedulePublish')}
      skipped={saved.data?.skipped}
      onChange={(patch: Partial<ScheduleForm>) =>
        save.mutate(toSchedule({ ...form, ...patch }), {
          onError: (error: Error) => toast.error(error.message),
        })
      }
    >
      {t('scheduleHint', { time: form.time })}
    </SchedulePicker>
  )
}

type OutputChoice = 'table' | 'qa' | 'qa_llm' | 'corpus'

function outputKindOf(choice: OutputChoice): 'table' | 'qa' | 'corpus' {
  return choice === 'qa_llm' ? 'qa' : choice
}

function RunStatus({ runId, qa }: { runId: string; qa: boolean }) {
  const t = useTranslations('recipes')
  const { data: run } = useJobRun(runId)
  if (!run) return null
  if (run.status === 'succeeded') {
    return (
      <Link
        className="btn btn-primary"
        href={qa ? `/drafts/runs/${runId}` : `/runs/${runId}/review`}
      >
        {t('review')}
      </Link>
    )
  }
  return (
    <span className="hint">
      {t(`runStatus.${run.status === 'failed' ? 'failed' : 'running'}`)}
      {run.error ? ` — ${run.error}` : ''}
    </span>
  )
}

function Editor({ recipe }: { recipe: SourceRecipe }) {
  const t = useTranslations('recipes')
  const save = useUpdateRecipe(recipe.id)
  const run = useRunRecipe(recipe.id)
  const [steps, setSteps] = useState<RecipeStep[]>(recipe.steps)
  const [targetRepo, setTargetRepo] = useState(recipe.target_repo)
  const [visibility, setVisibility] = useState(recipe.visibility)
  const [outputKind, setOutputKind] = useState<OutputChoice>(
    recipe.output_kind === 'qa'
      ? recipe.output_options?.generator === 'llm'
        ? 'qa_llm'
        : 'qa'
      : recipe.output_kind === 'corpus'
        ? 'corpus'
        : 'table',
  )
  const [corpus, setCorpus] = useState({
    text_template: String(recipe.output_options?.text_template ?? ''),
    title_template: String(recipe.output_options?.title_template ?? ''),
    id_column: String(recipe.output_options?.id_column ?? ''),
    chunk_chars: recipe.output_options?.chunk_chars
      ? String(recipe.output_options.chunk_chars)
      : '',
    metadata_columns: (recipe.output_options?.metadata_columns as string[] | undefined) ?? [],
  })
  const [llm, setLlm] = useState({
    subject: String(recipe.output_options?.subject ?? ''),
    group_by: String(recipe.output_options?.group_by ?? ''),
    group_size: Number(recipe.output_options?.group_size ?? 20),
    pairs_per_group: Number(recipe.output_options?.pairs_per_group ?? 5),
    row_template: String(recipe.output_options?.row_template ?? ''),
  })
  const [templates, setTemplates] = useState<FactTemplateForm[]>(
    ((recipe.output_options?.templates as FactTemplateForm[]) ?? []).map((tpl) => ({
      question: tpl.question ?? '',
      answer: tpl.answer ?? '',
      category: tpl.category ?? '',
    })),
  )
  const [keyColumn, setKeyColumn] = useState(String(recipe.output_options?.key_column ?? ''))
  const [debounced, setDebounced] = useState<RecipeStep[]>(recipe.steps)
  const [runId, setRunId] = useState<string | null>(null)
  const [adding, setAdding] = useState<StepOp>('select')

  // The preview follows the steps, a moment after the last change.
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(steps), PREVIEW_DELAY_MS)
    return () => clearTimeout(timer)
  }, [steps])
  const preview = useRecipePreview(recipe.id, debounced)
  const data = preview.data
  const outputOptions = useMemo(
    () =>
      outputKind === 'corpus'
        ? corpusOptions(corpus)
        : outputKind === 'qa_llm'
          ? Object.fromEntries(
              Object.entries({ generator: 'llm', ...llm }).filter(([, v]) => v !== ''),
            )
          : outputKind === 'qa'
            ? {
                generator: 'facts',
                templates: templates
                  .filter((tpl) => tpl.question.trim() && tpl.answer.trim())
                  .map((tpl) => {
                    const out: Record<string, string> = {
                      question: tpl.question,
                      answer: tpl.answer,
                    }
                    if (tpl.category) out.category = tpl.category
                    return out
                  }),
                ...(keyColumn ? { key_column: keyColumn } : {}),
              }
            : {},
    [outputKind, templates, keyColumn, llm, corpus],
  )
  const dirty = useMemo(
    () =>
      JSON.stringify(steps) !== JSON.stringify(recipe.steps) ||
      targetRepo !== recipe.target_repo ||
      visibility !== recipe.visibility ||
      outputKindOf(outputKind) !== recipe.output_kind ||
      JSON.stringify(outputOptions) !== JSON.stringify(recipe.output_options ?? {}),
    [steps, targetRepo, visibility, outputKind, outputOptions, recipe],
  )

  const persist = () =>
    save
      .mutateAsync({
        steps,
        target_repo: targetRepo,
        visibility,
        output_kind: outputKindOf(outputKind),
        output_options: outputOptions,
      })
      .then(
        () => toast.success(t('saved')),
        (e: Error) => {
          toast.error(e.message)
          throw e
        },
      )

  const start = async () => {
    if (dirty) await persist()
    run.mutate(undefined, {
      onSuccess: (started) => setRunId(started.id),
      onError: (e: Error) => toast.error(e.message),
    })
  }

  const columnsAtEnd = data ? (data.schema ?? []) : []

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      <div className="page-head">
        <div>
          <h1 className="page-title">{recipe.name}</h1>
          <p className="page-sub">{t('subtitle')}</p>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {runId && <RunStatus runId={runId} qa={outputKind === 'qa' || outputKind === 'qa_llm'} />}
          <button
            className="btn btn-outline"
            type="button"
            disabled={!dirty || save.isPending}
            onClick={() => void persist().catch(() => undefined)}
          >
            {t('save')}
          </button>
          <button
            className="btn btn-primary"
            type="button"
            disabled={run.isPending || save.isPending}
            onClick={() => void start().catch(() => undefined)}
          >
            <Icon name="play" />
            {t('run')}
          </button>
        </div>
      </div>

      <div className="card">
        <div className="card-body" style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          <label className="label">
            {t('targetRepo')}
            <input
              className="input mono"
              value={targetRepo}
              maxLength={193}
              onChange={(e) => setTargetRepo(e.target.value)}
            />
          </label>
          <label className="label">
            {t('visibility')}
            <select
              className="input"
              value={visibility}
              onChange={(e) => setVisibility(e.target.value as 'private' | 'public')}
            >
              <option value="private">{t('private')}</option>
              <option value="public">{t('public')}</option>
            </select>
          </label>
          <label className="label">
            {t('output')}
            <select
              className="input"
              value={outputKind}
              onChange={(e) => setOutputKind(e.target.value as OutputChoice)}
            >
              <option value="table">{t('outputTable')}</option>
              <option value="qa">{t('outputFacts')}</option>
              <option value="qa_llm">{t('outputLlm')}</option>
              <option value="corpus">{t('outputCorpus')}</option>
            </select>
          </label>
        </div>
        {outputKind === 'qa' && (
          <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div className="card-title">{t('templates')}</div>
            <div className="hint">{t('templatesHint', { syntax: TEMPLATE_SYNTAX })}</div>
            {templates.map((tpl, i) => (
              // Templates have no id: their position is it.
              <div
                // oxlint-disable-next-line react/no-array-index-key
                key={`tpl-${i}`}
                style={{ display: 'grid', gridTemplateColumns: '2fr 2fr 1fr auto', gap: 6 }}
              >
                <input
                  className="input"
                  aria-label={t('question')}
                  placeholder={QUESTION_EXAMPLE}
                  value={tpl.question}
                  onChange={(e) =>
                    setTemplates(
                      templates.map((x, j) => (j === i ? { ...x, question: e.target.value } : x)),
                    )
                  }
                />
                <input
                  className="input"
                  aria-label={t('answer')}
                  placeholder={ANSWER_EXAMPLE}
                  value={tpl.answer}
                  onChange={(e) =>
                    setTemplates(
                      templates.map((x, j) => (j === i ? { ...x, answer: e.target.value } : x)),
                    )
                  }
                />
                <input
                  className="input"
                  aria-label={t('category')}
                  placeholder={t('category')}
                  value={tpl.category}
                  onChange={(e) =>
                    setTemplates(
                      templates.map((x, j) => (j === i ? { ...x, category: e.target.value } : x)),
                    )
                  }
                />
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => setTemplates(templates.filter((_, j) => j !== i))}
                >
                  {t('remove')}
                </button>
              </div>
            ))}
            <div style={{ display: 'flex', gap: 8, alignItems: 'end' }}>
              <button
                type="button"
                className="btn btn-outline btn-sm"
                onClick={() =>
                  setTemplates([...templates, { question: '', answer: '', category: '' }])
                }
              >
                <Icon name="plus" />
                {t('addTemplate')}
              </button>
              <label className="label">
                {t('keyColumn')}
                <select
                  className="input"
                  value={keyColumn}
                  onChange={(e) => setKeyColumn(e.target.value)}
                >
                  <option value="">—</option>
                  {columnsAtEnd.map((c) => (
                    <option key={c.name} value={c.name}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </div>
        )}
        {outputKind === 'qa_llm' && (
          <div
            className="card-body"
            style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}
          >
            <label className="label">
              {t('llmSubject')}
              <input
                className="input"
                value={llm.subject}
                maxLength={200}
                onChange={(e) => setLlm({ ...llm, subject: e.target.value })}
              />
            </label>
            <label className="label">
              {t('llmGroupBy')}
              <select
                className="input"
                value={llm.group_by}
                onChange={(e) => setLlm({ ...llm, group_by: e.target.value })}
              >
                <option value="">{t('llmEveryN')}</option>
                {columnsAtEnd.map((c) => (
                  <option key={c.name} value={c.name}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="label">
              {t('llmGroupSize')}
              <input
                className="input"
                type="number"
                min={1}
                max={500}
                value={llm.group_size}
                onChange={(e) => setLlm({ ...llm, group_size: Number(e.target.value) || 1 })}
              />
            </label>
            <label className="label">
              {t('llmPairs')}
              <input
                className="input"
                type="number"
                min={1}
                max={20}
                value={llm.pairs_per_group}
                onChange={(e) => setLlm({ ...llm, pairs_per_group: Number(e.target.value) || 1 })}
              />
            </label>
            <label className="label" style={{ gridColumn: '1 / -1' }}>
              {t('llmRowTemplate')}
              <input
                className="input"
                value={llm.row_template}
                maxLength={2000}
                placeholder={ANSWER_EXAMPLE}
                onChange={(e) => setLlm({ ...llm, row_template: e.target.value })}
              />
            </label>
          </div>
        )}
        {outputKind === 'corpus' && (
          <div
            className="card-body"
            style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}
          >
            <div className="hint" style={{ gridColumn: '1 / -1' }}>
              {t('corpusHint', { syntax: TEMPLATE_SYNTAX })}
            </div>
            <label className="label" style={{ gridColumn: '1 / -1' }}>
              {t('corpusText')}
              <textarea
                className="input"
                rows={3}
                value={corpus.text_template}
                maxLength={4000}
                placeholder={ANSWER_EXAMPLE}
                onChange={(e) => setCorpus({ ...corpus, text_template: e.target.value })}
              />
            </label>
            <label className="label">
              {t('corpusTitle')}
              <input
                className="input"
                value={corpus.title_template}
                maxLength={1000}
                onChange={(e) => setCorpus({ ...corpus, title_template: e.target.value })}
              />
            </label>
            <label className="label">
              {t('corpusId')}
              <select
                className="input"
                value={corpus.id_column}
                onChange={(e) => setCorpus({ ...corpus, id_column: e.target.value })}
              >
                <option value="">{t('corpusIdPosition')}</option>
                {columnsAtEnd.map((c) => (
                  <option key={c.name} value={c.name}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="label">
              {t('corpusChunk')}
              <input
                className="input"
                type="number"
                min={200}
                max={20000}
                value={corpus.chunk_chars}
                placeholder={t('corpusChunkNone')}
                onChange={(e) => setCorpus({ ...corpus, chunk_chars: e.target.value })}
              />
            </label>
            <label className="label">
              {t('corpusMetadata')}
              <select
                className="input"
                multiple
                value={corpus.metadata_columns}
                onChange={(e) =>
                  setCorpus({
                    ...corpus,
                    metadata_columns: Array.from(e.target.selectedOptions, (o) => o.value),
                  })
                }
              >
                {columnsAtEnd.map((c) => (
                  <option key={c.name} value={c.name}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
        )}
        <div className="card-body">
          <RecipeSchedule recipeId={recipe.id} />
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(280px, 1fr) 2fr', gap: 18 }}>
        <div className="card">
          <div className="card-head">
            <div>
              <div className="card-title">{t('steps')}</div>
              <div className="card-desc">{t('sourceRows', { rows: data?.source_rows ?? '…' })}</div>
            </div>
          </div>
          <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {steps.length === 0 && <p className="hint">{t('noSteps')}</p>}
            {steps.map((step, i) => {
              const failing = data?.error?.step === i
              return (
                // Steps have no id: their position in the recipe is it.
                <div
                  // oxlint-disable-next-line react/no-array-index-key
                  key={`${i}:${step.op}`}
                  className="card"
                  style={{ borderColor: failing ? 'var(--destructive, #dc2626)' : undefined }}
                >
                  <div
                    className="card-body"
                    style={{ display: 'flex', flexDirection: 'column', gap: 6 }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <strong>
                        {i + 1}. {t(`ops.${step.op as StepOp}`)}
                      </strong>
                      <span className="hint">
                        {data?.step_rows?.[i] !== undefined
                          ? t('rowsAfter', { rows: data.step_rows[i] })
                          : ''}
                      </span>
                    </div>
                    <StepFields
                      step={step}
                      columns={columnsBefore(data, i)}
                      onChange={(next) => setSteps(replaceStep(steps, i, next))}
                    />
                    {failing && (
                      <p className="hint" role="alert">
                        {data?.error?.message}
                      </p>
                    )}
                    <div style={{ display: 'flex', gap: 6 }}>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() => setSteps(moveStep(steps, i, -1))}
                        disabled={i === 0}
                      >
                        {t('up')}
                      </button>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() => setSteps(moveStep(steps, i, 1))}
                        disabled={i === steps.length - 1}
                      >
                        {t('down')}
                      </button>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() => setSteps(removeStep(steps, i))}
                      >
                        {t('remove')}
                      </button>
                    </div>
                  </div>
                </div>
              )
            })}
            <div style={{ display: 'flex', gap: 6 }}>
              <select
                className="input"
                aria-label={t('newStep')}
                value={adding}
                onChange={(e) => setAdding(e.target.value as StepOp)}
              >
                {STEP_OPS.map((op) => (
                  <option key={op} value={op}>
                    {t(`ops.${op}`)}
                  </option>
                ))}
              </select>
              <button
                type="button"
                className="btn btn-outline"
                onClick={() => setSteps([...steps, newStep(adding, columnsAtEnd)])}
              >
                <Icon name="plus" />
                {t('addStep')}
              </button>
            </div>
          </div>
        </div>

        <div className="card">
          <div className="card-head">
            <div>
              <div className="card-title">{t('preview')}</div>
              <div className="card-desc">
                {preview.isFetching
                  ? t('previewing')
                  : data
                    ? t('previewRows', { rows: data.rows, shown: data.sample.length })
                    : ''}
              </div>
            </div>
          </div>
          <div className="card-body" style={{ overflowX: 'auto' }}>
            {preview.error && <p className="hint">{preview.error.message}</p>}
            {data?.error && data.error.step === null && (
              <p className="hint">{data.error.message}</p>
            )}
            {data?.llm && (
              <div style={{ marginBottom: 12 }} role={data.llm.missing ? 'alert' : undefined}>
                {data.llm.missing && <p className="hint">{data.llm.missing}</p>}
                {data.llm.error && <p className="hint">{data.llm.error}</p>}
                {data.llm.groups !== undefined && (
                  <p className="hint">
                    {t('llmEstimate', {
                      groups: data.llm.groups,
                      tokens: data.llm.estimated_tokens ?? 0,
                      limit: data.llm.limit ?? 0,
                    })}
                  </p>
                )}
              </div>
            )}
            {data?.pairs && (
              <div style={{ marginBottom: 12 }}>
                <div className="card-title">{t('pairsPreview')}</div>
                <p className="hint">{t('pairsSaveFirst')}</p>
                <ul>
                  {data.pairs.slice(0, 10).map((pair, i) => (
                    // oxlint-disable-next-line react/no-array-index-key
                    <li key={`pair-${i}`}>
                      {pair.error ? (
                        <span role="alert">{pair.error}</span>
                      ) : (
                        <>
                          <strong>{pair.question}</strong> — {pair.answer}
                        </>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {data && (
              <table className="table">
                <thead>
                  <tr>
                    {data.schema.map((c) => (
                      <th key={c.name}>
                        <span className="mono">{c.name}</span>
                        <div className="hint">{c.type}</div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.sample.map((row, r) => (
                    // Preview rows have no id of their own: their position is it.
                    // oxlint-disable-next-line react/no-array-index-key
                    <tr key={`row-${r}`}>
                      {data.schema.map((c) => (
                        <td key={c.name} className="mono">
                          {row[c.name] === null || row[c.name] === undefined
                            ? ''
                            : String(row[c.name])}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

// One recipe: its steps on the left, the live preview on the right (#306).
export function RecipeEditor({ recipeId }: { recipeId: string }) {
  const t = useTranslations('recipes')
  const { data: recipe, error, isPending } = useRecipe(recipeId)
  if (isPending) return <p className="hint">{t('loading')}</p>
  if (error || !recipe) return <p className="hint">{error?.message ?? t('notFound')}</p>
  return <Editor key={recipe.id} recipe={recipe} />
}
