'use client'

import { useEffect, useMemo, useState } from 'react'
import './quality.css'
import { Icon } from '@/components/app/icon'
import {
  useAnalyzeDataset,
  useCleanDataset,
  useDatasets,
  useHuggingFaceDatasets,
  useImportHuggingFaceDataset,
  useQAStats,
  useQualityRules,
  useResolvePair,
  useUpdateQualityRules,
} from '@/hooks'
import { useIsAdmin } from '@/hooks/use-auth'

const DEFAULT_SIMILARITY_THRESHOLD = 0.8
const DUPLICATES_PAGE_SIZE = 5

export default function QualityPage() {
  const { data: datasets, isPending: datasetsPending } = useDatasets()
  // The Hugging Face list only ever resolves client-side (no SSR hydration
  // boundary for it) — gating everything it feeds on `mounted` keeps the
  // first render identical on the server and the client, so hydration has
  // nothing to mismatch on. It flips on right after that first paint.
  const [mounted, setMounted] = useState(false)
  useEffect(() => setMounted(true), [])
  const [selectedDataset, setSelectedDataset] = useState('')
  const [threshold, setThreshold] = useState(DEFAULT_SIMILARITY_THRESHOLD)
  const [dismissedIds, setDismissedIds] = useState<Set<string>>(new Set())
  const [showAllDuplicates, setShowAllDuplicates] = useState(false)
  const [activeTab, setActiveTab] = useState<'pending' | 'resolved'>('pending')

  useEffect(() => {
    if (!selectedDataset && datasets && datasets.length > 0) {
      setSelectedDataset(datasets[0].name)
    }
  }, [datasets, selectedDataset])

  // Persisted quality rules (min answer length, rejection threshold, auto
  // rejection at generation). Editable here; saved via PUT /quality-rules.
  const rulesQuery = useQualityRules()
  const updateRulesMutation = useUpdateQualityRules()
  const isAdmin = useIsAdmin()
  const [draftRules, setDraftRules] = useState<{
    min_answer_words: number
    reject_below_confidence: number
    auto_reject_enabled: boolean
  } | null>(null)

  const savedRules = rulesQuery.data
  const rules = draftRules ?? {
    min_answer_words: savedRules?.min_answer_words ?? 12,
    reject_below_confidence: savedRules?.reject_below_confidence ?? 0.8,
    auto_reject_enabled: savedRules?.auto_reject_enabled ?? false,
  }
  const rulesDirty = draftRules !== null
  const scoreThreshold = savedRules?.reject_below_confidence ?? 0.8

  // Score stats are aggregated server-side over the whole dataset (see
  // GET /q_a/{dataset}/stats) — no client-side sampling cap.
  const statsQuery = useQAStats(selectedDataset, {
    scoreThreshold,
    enabled: !!selectedDataset,
  })

  const analyzeMutation = useAnalyzeDataset()
  const cleanMutation = useCleanDataset()
  const resolvePairMutation = useResolvePair()

  // Datasets that only exist on the Hub so far (not already analyzable
  // locally) — offered in the selector as an "import, then analyze" action,
  // since analysis (duplicates, stats, rules) only ever runs over local Q/A.
  const { data: hfDatasetsData, isPending: hfDatasetsPending } = useHuggingFaceDatasets()
  const importHfMutation = useImportHuggingFaceDataset()
  const localDatasetNames = useMemo(
    () => new Set(datasets?.map((d) => d.name)),
    [datasets],
  )
  const importableHfDatasets = useMemo(
    () =>
      !mounted
        ? []
        : (hfDatasetsData?.datasets ?? []).filter(
            (d) => !localDatasetNames.has(d.id.split('/').pop() || d.id),
          ),
    [mounted, hfDatasetsData, localDatasetNames],
  )

  const handleSelectDataset = (value: string) => {
    if (value.startsWith('hf:')) {
      const repoId = value.slice(3)
      importHfMutation.mutate(
        { repoId },
        { onSuccess: (result) => setSelectedDataset(result.dataset_name) },
      )
      return
    }
    setSelectedDataset(value)
  }

  const handleResolvePair = (removeId: string, question: string) => {
    if (!selectedDataset) return
    const confirmed = window.confirm(
      `Delete "${question}" and keep the other one? This can't be undone.`,
    )
    if (!confirmed) return
    resolvePairMutation.mutate(
      { datasetId: selectedDataset, removeId },
      // Refresh the pair list — deleting one record can dissolve several pairs.
      { onSuccess: () => analyzeMutation.mutate({ datasetId: selectedDataset, threshold }) },
    )
  }

  const handleSaveRules = () => {
    if (!draftRules) return
    updateRulesMutation.mutate(draftRules, { onSuccess: () => setDraftRules(null) })
  }

  useEffect(() => {
    if (!selectedDataset) return
    setDismissedIds(new Set())
    setShowAllDuplicates(false)
    analyzeMutation.mutate({ datasetId: selectedDataset, threshold })
    // Only re-run when the dataset changes; a threshold edit is applied via
    // the "Re-run analysis" button so typing doesn't spam requests.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedDataset])

  const handleReanalyze = () => {
    if (!selectedDataset) return
    setDismissedIds(new Set())
    analyzeMutation.mutate({ datasetId: selectedDataset, threshold })
  }

  const handleClean = () => {
    if (!selectedDataset) return
    const confirmed = window.confirm(
      `Remove the lower-confidence item of every pair at or above ${threshold} similarity? This can't be undone.`,
    )
    if (!confirmed) return

    cleanMutation.mutate(
      { datasetId: selectedDataset, threshold },
      { onSuccess: () => analyzeMutation.mutate({ datasetId: selectedDataset, threshold }) },
    )
  }

  const stats = statsQuery.data
  const scoreStats = {
    total: stats?.scored_count ?? 0,
    avg: stats?.average_score ?? null,
    below: stats?.below_threshold_count ?? 0,
    validated: stats?.validated_count ?? 0,
    buckets: stats?.distribution ?? [
      { label: '0.9–1.0', count: 0 },
      { label: '0.8–0.9', count: 0 },
      { label: '0.7–0.8', count: 0 },
      { label: '< 0.7', count: 0 },
    ],
  }

  const similarities = useMemo(
    () => analyzeMutation.data?.similarities ?? [],
    [analyzeMutation.data],
  )
  const pendingDuplicates = similarities.filter(
    (pair) => !dismissedIds.has(`${pair.record1_id}-${pair.record2_id}`),
  )
  const resolvedDuplicates = similarities.filter((pair) =>
    dismissedIds.has(`${pair.record1_id}-${pair.record2_id}`),
  )
  const visibleDuplicates = activeTab === 'pending' ? pendingDuplicates : resolvedDuplicates
  const shownDuplicates = showAllDuplicates
    ? visibleDuplicates
    : visibleDuplicates.slice(0, DUPLICATES_PAGE_SIZE)

  const hasAnyDataset = (datasets && datasets.length > 0) || importableHfDatasets.length > 0

  // `mounted` first: this branch swaps the whole page for an empty-state
  // card, so it must never fire during SSR or the client's pre-hydration
  // pass — a full-subtree mismatch there is far more disruptive than a
  // single mismatched attribute.
  if (mounted && !datasetsPending && !hfDatasetsPending && !hasAnyDataset) {
    return (
      <div className="quality-page">
        <div className="page-head">
          <div>
            <h1 className="page-title">Quality control</h1>
            <p className="page-sub">
              Detected duplicates, score distribution and pairs below the threshold — per dataset.
            </p>
          </div>
        </div>
        <div className="card">
          <div className="card-body" style={{ paddingTop: 20 }}>
            <p className="muted">No datasets available yet. Generate a dataset first.</p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="quality-page">
      <div className="page-head">
        <div>
          <h1 className="page-title">Quality control</h1>
          <p className="page-sub">
            Detected duplicates, score distribution and pairs below the threshold — per dataset.
          </p>
        </div>
        <div className="page-actions">
          <select
            className="select"
            style={{ width: 'auto' }}
            aria-label="Dataset"
            value={selectedDataset}
            onChange={(e) => handleSelectDataset(e.target.value)}
            disabled={
              !mounted ||
              datasetsPending ||
              importHfMutation.isPending ||
              (!datasets?.length && importableHfDatasets.length === 0)
            }
          >
            {/* Matches the initial "" value. Without it the browser shows the
                first option as if selected while React's value stays "" — so
                picking that option (e.g. the only Hugging Face repo) is not a
                change, onChange never fires and nothing gets imported. */}
            <option value="" disabled>
              Select a dataset…
            </option>
            {mounted &&
              datasets?.map((dataset) => (
                <option key={dataset.id} value={dataset.name}>
                  {dataset.name}
                </option>
              ))}
            {importableHfDatasets.length > 0 && (
              <optgroup label="Hugging Face (import to analyze)">
                {importableHfDatasets.map((hfDataset) => (
                  <option key={hfDataset.id} value={`hf:${hfDataset.id}`}>
                    {hfDataset.id}
                  </option>
                ))}
              </optgroup>
            )}
          </select>
          <button
            className="btn btn-primary"
            onClick={handleReanalyze}
            disabled={!selectedDataset || analyzeMutation.isPending}
          >
            <Icon
              name={analyzeMutation.isPending ? 'loader' : 'play'}
              className={analyzeMutation.isPending ? 'animate-spin' : undefined}
            />
            {analyzeMutation.isPending ? 'Analyzing…' : 'Re-run analysis'}
          </button>
        </div>
      </div>
      {importHfMutation.isPending && (
        <p className="hint" style={{ marginTop: -8, marginBottom: 12 }}>
          Importing from Hugging Face…
        </p>
      )}
      {importHfMutation.isError && (
        <p className="hint" style={{ marginTop: -8, marginBottom: 12, color: 'var(--destructive)' }}>
          {importHfMutation.error instanceof Error
            ? importHfMutation.error.message
            : 'Failed to import the Hugging Face dataset'}
        </p>
      )}

      <div className="stat-grid" style={{ marginBottom: 18 }}>
        <div className="card stat">
          <div className="stat-top">
            <span className="stat-label">Average score</span>
            <span className="stat-ic">
              <Icon name="shield" />
            </span>
          </div>
          <div className="stat-val">
            {scoreStats.avg !== null ? scoreStats.avg.toFixed(2) : '—'}
          </div>
          <div className="stat-delta muted">
            {stats ? `${stats.scored_count} of ${stats.total_count} scored` : '—'}
          </div>
        </div>
        <div className="card stat">
          <div className="stat-top">
            <span className="stat-label">Duplicates</span>
            <span className="stat-ic">
              <Icon name="copyCheck" />
            </span>
          </div>
          <div className="stat-val">{analyzeMutation.data?.similar_pairs_found ?? 0}</div>
          <div className="stat-delta muted">{pendingDuplicates.length} to arbitrate</div>
        </div>
        <div className="card stat">
          <div className="stat-top">
            <span className="stat-label">Below {scoreThreshold.toFixed(2)} threshold</span>
            <span className="stat-ic">
              <Icon name="alert" />
            </span>
          </div>
          {/* With nothing scored, "0 below" would read as "all good". */}
          <div className="stat-val">{scoreStats.total ? scoreStats.below : '—'}</div>
          <div className="stat-delta muted">
            {scoreStats.total
              ? `${((scoreStats.below / scoreStats.total) * 100).toFixed(1)}% of the dataset`
              : 'No scores'}
          </div>
        </div>
        <div className="card stat">
          <div className="stat-top">
            <span className="stat-label">Validated</span>
            <span className="stat-ic">
              <Icon name="check" />
            </span>
          </div>
          <div className="stat-val">{scoreStats.total ? scoreStats.validated : '—'}</div>
          <div className="stat-delta muted">
            {scoreStats.total
              ? `${((scoreStats.validated / scoreStats.total) * 100).toFixed(1)}%`
              : 'No scores'}
          </div>
        </div>
      </div>

      <div className="grid-2" style={{ marginBottom: 18 }}>
        <div className="card">
          <div className="card-head">
            <div>
              <div className="card-title">Score distribution</div>
            </div>
          </div>
          <div className="card-body" style={{ paddingTop: 6 }}>
            {/* isPending (not isLoading) so a paused query — the browser
                reports offline — still shows the loading line. It must be
                gated on selectedDataset: while none is picked the query is
                disabled, and a disabled query stays `pending` forever. */}
            {selectedDataset && statsQuery.isPending && <p className="muted">Loading scores…</p>}
            {!(selectedDataset && statsQuery.isPending) &&
              scoreStats.total === 0 &&
              (stats?.total_count ? (
                <p className="muted">
                  None of the {stats.total_count} pairs has a confidence score — datasets
                  imported from Hugging Face usually don&apos;t carry one, so there is nothing to
                  distribute or validate.
                </p>
              ) : (
                <p className="muted">No scored Q&amp;A items for this dataset yet.</p>
              ))}
            {scoreStats.buckets.map((bucket, i) => (
              <div className="bar-row" key={bucket.label}>
                <span className="bl">{bucket.label}</span>
                <div className="progress" style={{ flex: 1 }}>
                  <span
                    style={{
                      width: scoreStats.total
                        ? `${(bucket.count / scoreStats.total) * 100}%`
                        : '0%',
                      background:
                        i === 2 ? 'var(--warning)' : i === 3 ? 'var(--destructive)' : undefined,
                    }}
                  />
                </div>
                <span className="bv">{bucket.count}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="card">
          <div className="card-head">
            <div>
              <div className="card-title">Quality rules</div>
            </div>
          </div>
          <div
            className="card-body"
            style={{ paddingTop: 2, display: 'flex', flexDirection: 'column', gap: 12 }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 12,
              }}
            >
              <div>
                <div className="label">Duplicate threshold</div>
                <div className="hint">Text similarity used by analyze &amp; clean</div>
              </div>
              <input
                className="input"
                style={{ width: 90 }}
                type="number"
                min={0}
                max={1}
                step={0.01}
                value={threshold}
                onChange={(e) => setThreshold(Math.min(1, Math.max(0, Number(e.target.value))))}
              />
            </div>
            <hr className="sep" />
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 12,
              }}
            >
              <div>
                <div className="label">Quality rejection threshold</div>
                <div className="hint">Minimum confidence kept as &quot;validated&quot;</div>
              </div>
              <input
                className="input"
                style={{ width: 90 }}
                type="number"
                min={0}
                max={1}
                step={0.01}
                aria-label="Quality rejection threshold"
                value={rules.reject_below_confidence}
                onChange={(e) =>
                  setDraftRules({
                    ...rules,
                    reject_below_confidence: Math.min(1, Math.max(0, Number(e.target.value))),
                  })
                }
              />
            </div>
            <hr className="sep" />
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 12,
              }}
            >
              <div>
                <div className="label">Min. answer length</div>
                <div className="hint">Words (0 = no minimum)</div>
              </div>
              <input
                className="input"
                style={{ width: 90 }}
                type="number"
                min={0}
                step={1}
                aria-label="Minimum answer length in words"
                value={rules.min_answer_words}
                onChange={(e) =>
                  setDraftRules({
                    ...rules,
                    min_answer_words: Math.max(0, Math.round(Number(e.target.value))),
                  })
                }
              />
            </div>
            <hr className="sep" />
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div>
                <div className="label">Automatic rejection</div>
                <div className="hint">Applied at generation</div>
              </div>
              <button
                type="button"
                className={`switch${rules.auto_reject_enabled ? ' on' : ''}`}
                role="switch"
                aria-checked={rules.auto_reject_enabled}
                aria-label="Automatic rejection at generation"
                onClick={() =>
                  setDraftRules({ ...rules, auto_reject_enabled: !rules.auto_reject_enabled })
                }
              />
            </div>
            {rulesDirty && (
              <button
                className="btn btn-primary btn-sm"
                onClick={handleSaveRules}
                disabled={!isAdmin || updateRulesMutation.isPending}
              >
                <Icon
                  name={updateRulesMutation.isPending ? 'loader' : 'check'}
                  className={updateRulesMutation.isPending ? 'animate-spin' : undefined}
                />
                {updateRulesMutation.isPending ? 'Saving…' : 'Save rules'}
              </button>
            )}
            {rulesDirty && !isAdmin && (
              <p className="hint">Only an admin can save the quality rules.</p>
            )}
            {updateRulesMutation.isError && (
              <p className="hint" style={{ color: 'var(--destructive)' }}>
                {updateRulesMutation.error instanceof Error
                  ? updateRulesMutation.error.message
                  : 'Failed to save quality rules'}
              </p>
            )}
            <hr className="sep" />
            <button
              className="btn btn-outline btn-sm"
              onClick={handleClean}
              disabled={
                !selectedDataset || cleanMutation.isPending || pendingDuplicates.length === 0
              }
            >
              <Icon
                name={cleanMutation.isPending ? 'loader' : 'trash'}
                className={cleanMutation.isPending ? 'animate-spin' : undefined}
              />
              {cleanMutation.isPending ? 'Cleaning…' : 'Clean duplicates now'}
            </button>
            {cleanMutation.isSuccess && cleanMutation.data && (
              <p className="hint">
                Removed {cleanMutation.data.removed_records} of {cleanMutation.data.total_records}{' '}
                records.
              </p>
            )}
            {cleanMutation.isError && (
              <p className="hint" style={{ color: 'var(--destructive)' }}>
                {cleanMutation.error instanceof Error
                  ? cleanMutation.error.message
                  : 'Failed to clean duplicates'}
              </p>
            )}
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <div>
            <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Icon name="copyCheck" />
              Duplicates to arbitrate
            </div>
            <div className="card-desc">
              {selectedDataset
                ? `Semantically close pairs detected in ${selectedDataset}.`
                : 'Select a dataset to detect duplicates.'}
            </div>
          </div>
          <div className="tabs">
            <button
              className={`tab${activeTab === 'pending' ? ' active' : ''}`}
              onClick={() => setActiveTab('pending')}
            >
              To handle <span className="muted">{pendingDuplicates.length}</span>
            </button>
            <button
              className={`tab${activeTab === 'resolved' ? ' active' : ''}`}
              onClick={() => setActiveTab('resolved')}
            >
              Resolved <span className="muted">{resolvedDuplicates.length}</span>
            </button>
          </div>
        </div>
        <div className="card-body">
          {analyzeMutation.isPending && <p className="muted">Analyzing similarities…</p>}
          {resolvePairMutation.isError && (
            <p className="hint" style={{ color: 'var(--destructive)' }}>
              {resolvePairMutation.error instanceof Error
                ? resolvePairMutation.error.message
                : 'Failed to resolve the duplicate pair'}
            </p>
          )}
          {analyzeMutation.isError && (
            <p className="hint" style={{ color: 'var(--destructive)' }}>
              {analyzeMutation.error instanceof Error
                ? analyzeMutation.error.message
                : 'Failed to analyze similarities'}
            </p>
          )}
          {!analyzeMutation.isPending &&
            analyzeMutation.isSuccess &&
            visibleDuplicates.length === 0 && (
              <p className="muted">
                {activeTab === 'pending'
                  ? 'No duplicate pairs above the threshold.'
                  : 'Nothing kept yet.'}
              </p>
            )}

          {shownDuplicates.map((pair, index) => {
            const pairId = `${pair.record1_id}-${pair.record2_id}`
            return (
              <div className="dup" key={pairId}>
                <div className="dup-head">
                  <span className="ic">
                    <Icon name="copyCheck" />
                  </span>
                  <b style={{ fontSize: 13 }}>Duplicate #{index + 1}</b>
                  <span className="badge badge-warning">
                    similarity {(pair.similarity * 100).toFixed(0)}%
                  </span>
                </div>
                <div className="dup-pair">
                  <div className="dup-side">
                    <div className="q">{pair.question1}</div>
                  </div>
                  <div className="dup-mid">
                    <span className="pct">{(pair.similarity * 100).toFixed(0)}%</span>
                    <span className="muted" style={{ fontSize: 10 }}>
                      similar
                    </span>
                  </div>
                  <div className="dup-side">
                    <div className="q">{pair.question2}</div>
                  </div>
                </div>
                {activeTab === 'pending' && (
                  <div className="dup-foot">
                    <button
                      className="btn btn-ghost btn-sm"
                      onClick={() => setDismissedIds((prev) => new Set(prev).add(pairId))}
                    >
                      Keep both
                    </button>
                    <button
                      className="btn btn-outline btn-sm"
                      disabled={!isAdmin || resolvePairMutation.isPending}
                      title={isAdmin ? undefined : 'Admin only'}
                      onClick={() => handleResolvePair(pair.record2_id, pair.question2)}
                    >
                      <Icon name="check" />
                      Keep left
                    </button>
                    <button
                      className="btn btn-outline btn-sm"
                      disabled={!isAdmin || resolvePairMutation.isPending}
                      title={isAdmin ? undefined : 'Admin only'}
                      onClick={() => handleResolvePair(pair.record1_id, pair.question1)}
                    >
                      <Icon name="check" />
                      Keep right
                    </button>
                  </div>
                )}
              </div>
            )
          })}

          {visibleDuplicates.length > DUPLICATES_PAGE_SIZE && (
            <div style={{ display: 'flex', justifyContent: 'center', marginTop: 4 }}>
              <button
                className="btn btn-outline btn-sm"
                onClick={() => setShowAllDuplicates((prev) => !prev)}
              >
                <Icon name="chevronDown" />
                {showAllDuplicates
                  ? 'Show fewer'
                  : `View the remaining ${visibleDuplicates.length - DUPLICATES_PAGE_SIZE} duplicates`}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
