'use client'

import '../../datasets/hub.css'
import '../collections.css'
import { useParams } from 'next/navigation'
import { CollectionPage } from '@/components/collections/collection-page'

function decode(segment: string): string {
  try {
    return decodeURIComponent(segment)
  } catch {
    return segment
  }
}

// One collection: its build, then search, the retrieval test and how to use it.
export default function Page() {
  const params = useParams<{ id: string }>()
  const id = decode(params.id)
  return <CollectionPage key={id} id={id} />
}
