// bun applies a patch only to the exact version its patchedDependencies key
// names, and skips it without a word once that version is bumped. This test
// fails the bump instead, so the patch is checked and moved (or dropped).
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const manifest = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8')) as {
  patchedDependencies?: Record<string, string>
}

describe('patched dependencies', () => {
  const patched = Object.keys(manifest.patchedDependencies ?? {})

  it.each(patched)('%s is the installed version', (key) => {
    const at = key.lastIndexOf('@')
    const name = key.slice(0, at)
    const installed = JSON.parse(
      readFileSync(new URL(`./node_modules/${name}/package.json`, import.meta.url), 'utf8'),
    ) as { version: string }
    expect(`${name}@${installed.version}`, `regenerate the patch with bun patch ${name}`).toBe(key)
  })

  it('next keeps the HMR fix: a first restart does not reload every tab', () => {
    const source = readFileSync(
      new URL('./node_modules/next/dist/server/dev/hot-reloader-turbopack.js', import.meta.url),
      'utf8',
    )
    expect(source).toContain("initial.value.value.type !== 'restart'")
  })
})
