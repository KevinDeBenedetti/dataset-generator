import { describe, expect, it } from 'vitest'
import type { RecipeIn } from '@/api/types'
import {
  HF_REPO_PATTERN,
  defaultTargetRepo,
  docSelected,
  docsMode,
  findSource,
  selectsSomething,
  setDocsMode,
  setReadme,
  slugify,
  toggleDoc,
  toggleRepo,
} from './recipe-state'

const EMPTY: RecipeIn = { name: 'r', target_repo: 'kevin/r', include_profile: true, sources: [] }
const PICK = ['docs/a.md', 'docs/b.md']

describe('recipe edits', () => {
  it('adds a repo with its README and the default docs, then takes it out', () => {
    const added = toggleRepo(EMPTY, 'alpha', true)
    expect(added.sources).toEqual([{ repo: 'alpha', readme: true, docs: null }])
    expect(toggleRepo(added, 'alpha', true)).toBe(added)
    expect(toggleRepo(added, 'ALPHA', false).sources).toEqual([])
  })

  it('switches the README off for one repo only', () => {
    const two = toggleRepo(toggleRepo(EMPTY, 'alpha', true), 'beta', true)
    const changed = setReadme(two, 'beta', false)
    expect(findSource(changed, 'alpha')?.readme).toBe(true)
    expect(findSource(changed, 'beta')?.readme).toBe(false)
    expect(setReadme(EMPTY, 'nope', false)).toBe(EMPTY)
  })

  it('moves between default, custom and no docs', () => {
    const recipe = toggleRepo(EMPTY, 'alpha', true)
    expect(docsMode(findSource(recipe, 'alpha'))).toBe('default')

    const custom = setDocsMode(recipe, 'alpha', 'custom', PICK)
    expect(findSource(custom, 'alpha')?.docs).toEqual(PICK)
    expect(docsMode(findSource(custom, 'alpha'))).toBe('custom')

    const none = setDocsMode(custom, 'alpha', 'none', PICK)
    expect(findSource(none, 'alpha')?.docs).toEqual([])
    expect(docsMode(findSource(none, 'alpha'))).toBe('none')

    expect(findSource(setDocsMode(none, 'alpha', 'default', PICK), 'alpha')?.docs).toBeNull()
  })

  it('ticks a file: the default pick becomes a custom list first', () => {
    const recipe = toggleRepo(EMPTY, 'alpha', true)
    const without = toggleDoc(recipe, 'alpha', 'docs/b.md', PICK)
    expect(findSource(without, 'alpha')?.docs).toEqual(['docs/a.md'])
    const extra = toggleDoc(without, 'alpha', 'docs/c.md', PICK)
    expect(findSource(extra, 'alpha')?.docs).toEqual(['docs/a.md', 'docs/c.md'])

    expect(docSelected(findSource(recipe, 'alpha'), 'docs/b.md', PICK)).toBe(true)
    expect(docSelected(findSource(without, 'alpha'), 'docs/b.md', PICK)).toBe(false)
    expect(docSelected(undefined, 'docs/a.md', PICK)).toBe(false)
  })

  it('says whether there is anything to generate from', () => {
    expect(selectsSomething(EMPTY)).toBe(true)
    expect(selectsSomething({ ...EMPTY, include_profile: false })).toBe(false)
    expect(selectsSomething(toggleRepo({ ...EMPTY, include_profile: false }, 'a', true))).toBe(true)
  })
})

describe('target repo', () => {
  it('slugs a name into a valid Hub repo name', () => {
    expect(slugify('Portfolio Q&A — été')).toBe('portfolio-q-a-ete')
    expect(slugify('***')).toBe('dataset')
    expect(defaultTargetRepo('My docs', 'kevin')).toBe('kevin/my-docs')
    expect(defaultTargetRepo('My docs')).toBe('my-docs')
  })

  it('matches the server rule', () => {
    expect(HF_REPO_PATTERN.test('kevin/github-qa')).toBe(true)
    expect(HF_REPO_PATTERN.test('github-qa')).toBe(true)
    expect(HF_REPO_PATTERN.test('a/b/c')).toBe(false)
    expect(HF_REPO_PATTERN.test('not a repo')).toBe(false)
  })
})
