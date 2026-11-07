'use client'

import type { HubDatasetDetail } from '@/api/types'
import { Icon } from '@/components/app/icon'
import { compactJson } from './format'
import { Markdown } from './markdown'

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
          <Markdown>{markdown}</Markdown>
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
