'use client'

import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import type { RecipeIn } from '@/api/types'
import { Icon } from '@/components/app/icon'
import {
  useGitHubProfile,
  useGitHubRepos,
  useHubDatasets,
  useRecipes,
  useUpdateRecipe,
} from '@/hooks'
import { AccountCard, GitHubProblem } from './account-card'
import { NewRecipeForm, RecipeBar } from './recipe-bar'
import { toRecipeIn, toggleRepo } from './recipe-state'
import { RepoList } from './repo-list'
import { RepoPanel } from './repo-panel'

// Edits are shown at once and saved whole once they pause this long; a save
// is never sent while another is in flight, so they can't land out of order.
const SAVE_DELAY_MS = 500

export function GitHubPage() {
  const profile = useGitHubProfile()
  const repos = useGitHubRepos()
  const recipes = useRecipes()
  const hub = useHubDatasets()
  const update = useUpdateRecipe()

  const [recipeId, setRecipeId] = useState<string | null>(null)
  const [openRepo, setOpenRepo] = useState<string | null>(null)
  // The recipe being edited, ahead of what the server has saved.
  const [edit, setEdit] = useState<{ id: string; recipe: RecipeIn } | null>(null)

  const list = useMemo(() => recipes.data?.recipes ?? [], [recipes.data])
  const current = list.find((r) => r.id === recipeId) ?? list[0] ?? null
  const saved = current ? toRecipeIn(current) : null
  const working = edit && current && edit.id === current.id ? edit.recipe : saved
  const dirty = Boolean(
    edit &&
    saved &&
    edit.id === current?.id &&
    JSON.stringify(edit.recipe) !== JSON.stringify(saved),
  )

  useEffect(() => {
    if (!edit || !dirty || update.isPending) return
    const timer = setTimeout(() => {
      update.mutate(
        { id: edit.id, recipe: edit.recipe },
        {
          onError: (error) => {
            // The server refused: show what it has, and why.
            setEdit(null)
            toast.error(error.message)
          },
        },
      )
    }, SAVE_DELAY_MS)
    return () => clearTimeout(timer)
  }, [edit, dirty, update])

  const change = (recipe: RecipeIn) => {
    if (current) setEdit({ id: current.id, recipe })
  }
  const select = (id: string | null) => {
    setEdit(null)
    setRecipeId(id)
  }

  const repoList = repos.data?.repos ?? []
  const open = repoList.find((r) => r.name === openRepo) ?? null

  return (
    <div className="hub-page gh-page">
      <div className="page-head">
        <div>
          <h1 className="page-title">GitHub</h1>
          <p className="page-sub">
            Your public GitHub data, and the recipes that pick from it. A recipe generates a draft
            you review before it is published to its Hugging Face dataset.
          </p>
        </div>
      </div>

      {profile.error ? (
        <GitHubProblem error={profile.error} />
      ) : profile.data ? (
        <AccountCard profile={profile.data} />
      ) : (
        <div className="card hub-loading" aria-busy="true">
          <Icon name="loader" className="animate-spin" />
          Reading your GitHub account…
        </div>
      )}

      {profile.data && (
        <>
          {recipes.isPending ? null : current && working ? (
            <RecipeBar
              recipes={list}
              current={current}
              working={working}
              saving={update.isPending}
              dirty={dirty}
              namespace={hub.data?.namespace ?? null}
              onSelect={select}
              onChange={change}
            />
          ) : (
            <div className="card gh-recipe">
              <div className="card-title">Start a recipe</div>
              <p className="card-desc">
                A recipe picks the repos, READMEs and docs files a dataset is generated from, and
                names the Hugging Face dataset it publishes to.
              </p>
              <NewRecipeForm
                namespace={hub.data?.namespace ?? null}
                onCreated={(recipe) => select(recipe.id)}
              />
            </div>
          )}

          {repos.error && <GitHubProblem error={repos.error} />}
          {repos.isPending && (
            <div className="card hub-loading" aria-busy="true">
              <Icon name="loader" className="animate-spin" />
              Listing your repos…
            </div>
          )}
          {repos.data && (
            <div className={open ? 'gh-layout has-panel' : 'gh-layout'}>
              <RepoList
                repos={repoList}
                recipe={working}
                open={openRepo}
                onOpen={setOpenRepo}
                onToggle={(repo, on) => working && change(toggleRepo(working, repo, on))}
              />
              {open && (
                <RepoPanel
                  key={open.name}
                  owner={profile.data.login}
                  repo={open.name}
                  eligible={open.eligible}
                  recipe={working}
                  onChange={change}
                  onClose={() => setOpenRepo(null)}
                />
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}
