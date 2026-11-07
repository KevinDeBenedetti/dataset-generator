'use client'

import '../../../datasets/hub.css'
import '../../../github/github.css'
import { useParams } from 'next/navigation'
import { DraftReview } from '@/components/github/draft-review'

// One draft (a recipe run, a file or a web page): review it, then publish it.
export default function DraftReviewPage() {
  const params = useParams<{ id: string }>()
  return <DraftReview key={params.id} runId={params.id} />
}
