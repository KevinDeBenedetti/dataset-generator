'use client'

import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { HubDatasetDetail } from '@/api/types'
import { Icon } from '@/components/app/icon'
import { compactJson } from './format'

// The card is Markdown written by whoever owns the repo. react-markdown never
// renders raw HTML (no rehype-raw), links open in a new tab, and images become
// links: the production CSP only allows same-origin images, and a remote image
// would also tell its host who opened the page.
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

function MetadataValue({ value }: { value: unknown }) {
  if (Array.isArray(value) && value.every((v) => typeof v !== 'object' || v === null)) {
    return (
      <span className="hub-chips">
        {value.map((v) => (
          <span key={String(v)} className="tag">
            {String(v)}
          </span>
        ))}
      </span>
    )
  }
  if (value !== null && typeof value === 'object') {
    return <pre className="hub-pre">{JSON.stringify(value, null, 2)}</pre>
  }
  return <span>{typeof value === 'string' ? value : compactJson(value)}</span>
}

export function CardPanel({ detail }: { detail: HubDatasetDetail }) {
  const markdown = detail.card.markdown
  const metadata = Object.entries(detail.card.metadata ?? {})
  return (
    <div className="hub-card-tab">
      <article className="card hub-markdown">
        {markdown ? (
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={COMPONENTS}>
            {markdown}
          </ReactMarkdown>
        ) : (
          <p className="muted">
            This dataset has no card (README.md). A card describes the data, its sources and its
            license; the Hub shows it on the dataset page.
          </p>
        )}
      </article>
      {metadata.length > 0 && (
        <details className="card hub-meta">
          <summary>
            <Icon name="fileJson" className="ic-sm" />
            Card metadata
            <span className="muted">{metadata.length} field(s), from the README front matter</span>
          </summary>
          <dl className="hub-fields">
            {metadata.map(([key, value]) => (
              <div key={key} className="hub-field">
                <dt className="mono">{key}</dt>
                <dd>
                  <MetadataValue value={value} />
                </dd>
              </div>
            ))}
          </dl>
        </details>
      )}
    </div>
  )
}
