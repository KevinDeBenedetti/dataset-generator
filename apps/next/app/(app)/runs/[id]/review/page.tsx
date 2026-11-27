'use client'

import '../../../datasets/hub.css'
import { useParams } from 'next/navigation'
import { TabularReview } from '@/components/review/tabular-review'

// One recipe run's tabular draft: review it, then approve or reject it.
export default function TabularReviewPage() {
  const params = useParams<{ id: string }>()
  return <TabularReview key={params.id} runId={params.id} />
}
