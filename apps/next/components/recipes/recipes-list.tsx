'use client'

import Link from 'next/link'
import { useLocale, useTranslations } from 'next-intl'
import { toast } from 'sonner'
import {
  useDataSources,
  useDeleteRecipe,
  useRecipeRuns,
  useRecipes,
} from '@/hooks/use-data-sources'
import { reviewHref } from './recipe-state'

// Your recipes, and the runs waiting for a review.
export function RecipesList() {
  const t = useTranslations('recipes')
  const locale = useLocale()
  const { data, isPending, error } = useRecipes()
  const { data: sources } = useDataSources()
  const { data: runs } = useRecipeRuns()
  const remove = useDeleteRecipe()
  const names = new Map((sources?.data_sources ?? []).map((s) => [s.id, s.name]))
  const recipes = data?.recipes ?? []
  const waiting = (runs?.runs ?? []).filter((r) => r.to_review)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      <div className="page-head">
        <div>
          <h1 className="page-title">{t('title')}</h1>
          <p className="page-sub">{t('listSubtitle')}</p>
        </div>
        <Link className="btn btn-outline" href="/sources">
          {t('sources')}
        </Link>
      </div>

      {waiting.length > 0 && (
        <div className="card">
          <div className="card-head">
            <div className="card-title">{t('toReview')}</div>
          </div>
          <div className="card-body">
            <ul>
              {waiting.map((run) => (
                <li key={run.run_id}>
                  <Link className="underline" href={reviewHref(run.run_id, run.kind)}>
                    {run.recipe_name ?? run.run_id}
                  </Link>{' '}
                  <span className="hint">
                    {t('runRows', { rows: run.rows ?? 0 })}
                    {run.started_at ? ` · ${new Date(run.started_at).toLocaleString(locale)}` : ''}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      <div className="card">
        <div className="card-body">
          {isPending && <p className="hint">{t('loading')}</p>}
          {error && <p className="hint">{error.message}</p>}
          {!isPending && recipes.length === 0 && <p className="hint">{t('empty')}</p>}
          {recipes.length > 0 && (
            <table className="table">
              <thead>
                <tr>
                  <th>{t('name')}</th>
                  <th>{t('source')}</th>
                  <th>{t('targetRepo')}</th>
                  <th>{t('stepsCount')}</th>
                  <th>{t('actions')}</th>
                </tr>
              </thead>
              <tbody>
                {recipes.map((recipe) => (
                  <tr key={recipe.id}>
                    <td>
                      <Link className="underline" href={`/recipes/${recipe.id}`}>
                        {recipe.name}
                      </Link>
                    </td>
                    <td>{names.get(recipe.data_source_id) ?? '—'}</td>
                    <td className="mono">
                      {recipe.target_repo} · {t(recipe.visibility)}
                    </td>
                    <td>{recipe.steps.length}</td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-outline btn-sm"
                        disabled={remove.isPending}
                        onClick={() => {
                          if (window.confirm(t('confirmDelete', { name: recipe.name }))) {
                            remove.mutate(recipe.id, {
                              onError: (e: Error) => toast.error(e.message),
                            })
                          }
                        }}
                      >
                        {t('delete')}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}
