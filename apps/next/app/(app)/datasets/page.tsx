import './hub.css'
import { HubDatasetsList } from '@/components/hub'

// Published datasets, read from Hugging Face (the source of truth).
export default function DatasetsPage() {
  return <HubDatasetsList />
}
