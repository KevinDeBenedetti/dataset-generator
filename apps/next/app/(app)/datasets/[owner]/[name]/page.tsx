'use client'

import '../../hub.css'
import { Suspense } from 'react'
import { useParams } from 'next/navigation'
import { HubDatasetPage } from '@/components/hub'

// A malformed escape in a hand-typed URL must not crash the page: the API
// answers 404 to whatever is left.
function decode(segment: string): string {
  try {
    return decodeURIComponent(segment)
  } catch {
    return segment
  }
}

// One Hugging Face dataset: data, card, statistics, files and history, all read
// from the Hub. The view (tab, version, split, filters…) lives in the URL.
export default function DatasetPage() {
  const params = useParams<{ owner: string; name: string }>()
  const repo = { owner: decode(params.owner), name: decode(params.name) }
  return (
    <Suspense>
      <HubDatasetPage key={`${repo.owner}/${repo.name}`} repo={repo} />
    </Suspense>
  )
}
