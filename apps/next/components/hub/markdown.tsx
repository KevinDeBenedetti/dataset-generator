'use client'

import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Icon } from '@/components/app/icon'

// Markdown written by whoever owns the repo (a dataset card, a README).
// react-markdown never renders raw HTML (no rehype-raw), links open in a new
// tab, and images become links: the production CSP only allows same-origin
// images, and a remote image would also tell its host who opened the page.
const COMPONENTS: Components = {
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  ),
  img: ({ src, alt }) =>
    typeof src === 'string' && src ? (
      <a href={src} target="_blank" rel="noopener noreferrer" className="hub-md-img">
        <Icon name="eye" className="ic-sm" />
        {alt || 'image'}
      </a>
    ) : null,
  table: ({ children }) => (
    <div className="hub-md-table">
      <table>{children}</table>
    </div>
  ),
}

/** Markdown someone else wrote (a dataset card, a README), rendered safely. */
export function Markdown({ children }: { children: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={COMPONENTS}>
      {children}
    </ReactMarkdown>
  )
}
