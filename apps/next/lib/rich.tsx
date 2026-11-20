import Link from 'next/link'
import type { ReactNode } from 'react'

// Tag renderers for `t.rich(...)` messages, defined once here: a renderer
// written inline in a component is a new function on every render.
export const rich = {
  strong: (chunks: ReactNode) => <strong>{chunks}</strong>,
  b: (chunks: ReactNode) => <b>{chunks}</b>,
  mono: (chunks: ReactNode) => <span className="mono">{chunks}</span>,
  code: (chunks: ReactNode) => <code>{chunks}</code>,
}

/** A renderer that turns a tag of a rich message into a link to `href`. */
export function richLink(href: string, className?: string) {
  return function renderLink(chunks: ReactNode) {
    return (
      <Link href={href} className={className}>
        {chunks}
      </Link>
    )
  }
}
