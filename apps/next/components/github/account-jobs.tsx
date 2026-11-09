'use client'

import { Icon } from '@/components/app/icon'
import { JobCard } from '@/components/jobs/job-card'
import { useJobs } from '@/hooks'

/** The datasets built from the whole account (GET /jobs): the Q&A dataset and
 * the knowledge corpus, each run when you start it. */
export function AccountJobs() {
  const jobs = useJobs()
  return (
    <section className="gh-jobs" aria-labelledby="gh-jobs-title">
      <div className="gh-section-head">
        <h2 id="gh-jobs-title" className="card-title">
          From your whole account
        </h2>
        <p className="hint">
          Built from every public repo of your account, and published to the dataset repos saved in
          Settings.
        </p>
      </div>
      {jobs.error ? (
        <p className="hint job-error">
          {jobs.error instanceof Error ? jobs.error.message : 'Failed to load the jobs'}
        </p>
      ) : jobs.data ? (
        <div className="grid-2 gh-jobs-grid">
          {jobs.data.map((job) => (
            <JobCard key={job.id} job={job} />
          ))}
        </div>
      ) : (
        <div className="card hub-loading" aria-busy="true">
          <Icon name="loader" className="animate-spin" />
          Loading the jobs…
        </div>
      )}
    </section>
  )
}
