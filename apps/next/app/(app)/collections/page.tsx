import '../datasets/hub.css'
import './collections.css'
import { Suspense } from 'react'
import { CollectionsPage } from '@/components/collections/collections-page'

// Qdrant collections built from splits of your Hugging Face datasets.
// Suspense: the page reads ?repo= (a dataset page's "Build a collection").
export default function Page() {
  return (
    <Suspense>
      <CollectionsPage />
    </Suspense>
  )
}
