'use client'

import type { ResumeOut } from '@/api/types'
import { Icon } from '@/components/app/icon'
import { useResume } from '@/hooks'
import { ResumeDataset } from './resume-dataset'

// The server keeps http(s) links only; the label is the host, not the URL.
function hostOf(url: string): string {
  try {
    return new URL(url).host
  } catch {
    return url
  }
}

function ResumeBody({ resume }: { resume: ResumeOut }) {
  const { basics } = resume
  const contact = [basics.location, basics.email, basics.phone].filter(Boolean)
  const facts = basics.facts ?? []
  const links = basics.links ?? []
  return (
    <div className="rs-body">
      <div>
        {basics.name && <div className="rs-name">{basics.name}</div>}
        {basics.headline && <div className="rs-headline">{basics.headline}</div>}
        <div className="rs-contact">
          {contact.map((value) => (
            <span key={value}>{value}</span>
          ))}
          {basics.website && (
            <a href={basics.website} target="_blank" rel="noopener noreferrer">
              {hostOf(basics.website)}
            </a>
          )}
          {links.map((link) => (
            <a key={link.url} href={link.url} target="_blank" rel="noopener noreferrer">
              {link.label}
            </a>
          ))}
        </div>
        {facts.length > 0 && (
          <ul className="rs-facts">
            {facts.map((fact) => (
              <li key={fact}>{fact}</li>
            ))}
          </ul>
        )}
      </div>

      {resume.summary && (
        <section>
          <h3 className="rs-section-title">Summary</h3>
          <p className="rs-text">{resume.summary}</p>
        </section>
      )}

      {resume.sections.map((section) => (
        <section key={section.key}>
          <h3 className="rs-section-title">{section.title}</h3>
          <ul className="rs-items">
            {section.items.map((item) => (
              <li key={item.id}>
                <div className="rs-item-head">
                  <span className="rs-item-title">
                    {item.url ? (
                      <a href={item.url} target="_blank" rel="noopener noreferrer">
                        {item.title}
                      </a>
                    ) : (
                      item.title
                    )}
                  </span>
                  {item.period && <span className="rs-item-period">{item.period}</span>}
                </div>
                {item.subtitle && <div className="rs-item-sub">{item.subtitle}</div>}
                {item.text && <p className="rs-text">{item.text}</p>}
                {(item.keywords ?? []).length > 0 && (
                  <div className="rs-keywords">
                    {/* Each keyword comes once (the server dedupes them). */}
                    {(item.keywords ?? []).map((keyword) => (
                      <span key={keyword} className="tag">
                        {keyword}
                      </span>
                    ))}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </section>
      ))}

      {!resume.summary && resume.sections.length === 0 && (
        <p className="muted">Nothing visible in this resume yet.</p>
      )}
    </div>
  )
}

/** The resume picked in the list, read as text. */
export function ResumeView({ id, onClose }: { id: string; onClose: () => void }) {
  const query = useResume(id)
  const resume = query.data
  return (
    <section className="card gh-panel" aria-label={resume?.name ?? 'Resume'}>
      <header className="gh-panel-head">
        <div>
          <div className="card-title">{resume?.name ?? 'Resume'}</div>
          {resume && <div className="hint mono">{resume.slug}</div>}
        </div>
        <div className="gh-panel-actions">
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close">
            <Icon name="x" />
          </button>
        </div>
      </header>
      <div className="gh-panel-body">
        {query.error ? (
          <p className="hub-error">{query.error.message}</p>
        ) : !resume ? (
          <p className="hint" aria-busy="true">
            <Icon name="loader" className="animate-spin" /> Reading the resume…
          </p>
        ) : (
          <>
            <ResumeDataset resume={resume} />
            <ResumeBody resume={resume} />
          </>
        )}
      </div>
    </section>
  )
}
