import { describe, expect, it } from 'vitest'
import en from './en.json'
import fr from './fr.json'

type Tree = { [key: string]: string | Tree }

function leaves(tree: Tree, prefix = ''): Record<string, string> {
  const all: Record<string, string> = {}
  for (const [key, value] of Object.entries(tree)) {
    const path = prefix ? `${prefix}.${key}` : key
    if (typeof value === 'string') all[path] = value
    else Object.assign(all, leaves(value, path))
  }
  return all
}

const placeholders = (text: string) => (text.match(/\{[a-zA-Z]+/g) ?? []).toSorted()

describe('messages', () => {
  const english = leaves(en)
  const french = leaves(fr)

  it('has the same keys in English and French', () => {
    expect(Object.keys(french).toSorted()).toEqual(Object.keys(english).toSorted())
  })

  it('has no empty message', () => {
    for (const [key, text] of [...Object.entries(english), ...Object.entries(french)]) {
      expect(text.trim(), key).not.toBe('')
    }
  })

  it('uses the same placeholders in both languages', () => {
    for (const [key, text] of Object.entries(english)) {
      expect(placeholders(french[key] ?? ''), key).toEqual(placeholders(text))
    }
  })
})
