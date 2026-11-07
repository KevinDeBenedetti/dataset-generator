import type { RecipeIn, RecipeOut, RecipeSource } from '@/api/types'

// Pure edits of a dataset recipe: what the GitHub page's toggles do. Each one
// returns a new recipe, saved whole (PUT /recipes/{id}).

/** How a repo's docs/ files are picked: the generation's default, a chosen
 * list, or none. */
export type DocsMode = 'default' | 'custom' | 'none'

// The server's rule for a Hugging Face repo id (schemas/recipes.py).
export const HF_REPO_PATTERN =
  /^(?:[A-Za-z0-9][A-Za-z0-9._-]{0,95}\/)?[A-Za-z0-9][A-Za-z0-9._-]{0,95}$/

const same = (a: string, b: string) => a.toLowerCase() === b.toLowerCase()

export function findSource(recipe: RecipeIn, repo: string): RecipeSource | undefined {
  return (recipe.sources ?? []).find((s) => same(s.repo, repo))
}

function replaceSource(recipe: RecipeIn, repo: string, source: RecipeSource | null): RecipeIn {
  const sources = recipe.sources ?? []
  const index = sources.findIndex((s) => same(s.repo, repo))
  if (source === null) {
    return { ...recipe, sources: sources.filter((_, i) => i !== index) }
  }
  if (index < 0) return { ...recipe, sources: [...sources, source] }
  return { ...recipe, sources: sources.map((s, i) => (i === index ? source : s)) }
}

/** Add a repo (README and the default docs pick) or take it out. */
export function toggleRepo(recipe: RecipeIn, repo: string, on: boolean): RecipeIn {
  if (on === Boolean(findSource(recipe, repo))) return recipe
  return replaceSource(recipe, repo, on ? { repo, readme: true, docs: null } : null)
}

export function setReadme(recipe: RecipeIn, repo: string, on: boolean): RecipeIn {
  const source = findSource(recipe, repo)
  return source ? replaceSource(recipe, repo, { ...source, readme: on }) : recipe
}

export function docsMode(source: RecipeSource | undefined): DocsMode {
  if (!source || source.docs == null) return 'default'
  return source.docs.length ? 'custom' : 'none'
}

/** Switch how docs are picked; going custom starts from the default pick. */
export function setDocsMode(
  recipe: RecipeIn,
  repo: string,
  mode: DocsMode,
  defaultPick: string[],
): RecipeIn {
  const source = findSource(recipe, repo)
  if (!source) return recipe
  const docs =
    mode === 'default'
      ? null
      : mode === 'none'
        ? []
        : source.docs?.length
          ? source.docs
          : [...defaultPick]
  return replaceSource(recipe, repo, { ...source, docs })
}

/** Tick or untick one docs file (a default pick becomes a custom list). */
export function toggleDoc(
  recipe: RecipeIn,
  repo: string,
  path: string,
  defaultPick: string[],
): RecipeIn {
  const source = findSource(recipe, repo)
  if (!source) return recipe
  const current = source.docs == null ? [...defaultPick] : [...source.docs]
  const docs = current.includes(path) ? current.filter((p) => p !== path) : [...current, path]
  return replaceSource(recipe, repo, { ...source, docs })
}

/** Is this docs file read by the generation, given how the repo picks them? */
export function docSelected(source: RecipeSource | undefined, path: string, defaultPick: string[]) {
  if (!source) return false
  return source.docs == null ? defaultPick.includes(path) : source.docs.includes(path)
}

/** The editable part of a saved recipe. */
export function toRecipeIn(recipe: RecipeOut): RecipeIn {
  return {
    name: recipe.name,
    target_repo: recipe.target_repo,
    include_profile: recipe.include_profile ?? true,
    sources: recipe.sources ?? [],
    model_ref: recipe.model_ref ?? null,
  }
}

/** A valid Hugging Face repo name from free text. */
export function slugify(name: string): string {
  const slug = name
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^A-Za-z0-9._-]+/g, '-')
    .replace(/^[-._]+|[-._]+$/g, '')
    .toLowerCase()
    .slice(0, 96)
  return slug || 'dataset'
}

/** Where a new recipe publishes by default: `<namespace>/<slug>`. */
export function defaultTargetRepo(name: string, namespace?: string | null): string {
  const slug = slugify(name)
  return namespace ? `${namespace}/${slug}` : slug
}

/** Something to generate from, at least. */
export function selectsSomething(recipe: RecipeIn): boolean {
  return Boolean(recipe.include_profile ?? true) || (recipe.sources ?? []).length > 0
}
