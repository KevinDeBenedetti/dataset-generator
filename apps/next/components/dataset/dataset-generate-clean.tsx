'use client'

import { Button } from '@/components/ui/button'
import { Loader2 } from 'lucide-react'
import { useGenerateStore } from '@/stores/generate'
import { useDatasetStore } from '@/stores/dataset'
import { useCleanDataset } from '@/hooks'

export function DatasetGenerateClean() {
  const generationStatus = useGenerateStore((state) => state.generationStatus)
  const dataset = useGenerateStore((state) => state.dataset)
  const analyzeStatus = useDatasetStore((state) => state.analyzeStatus)
  const cleanStatus = useDatasetStore((state) => state.cleanStatus)

  const cleanMutation = useCleanDataset()

  const datasetId = dataset?.id || ''

  const isAnyProcessing =
    generationStatus === 'pending' ||
    analyzeStatus === 'pending' ||
    cleanStatus === 'pending'

  const handleClean = async () => {
    if (!datasetId) {
      console.error('No dataset ID available for cleaning')
      return
    }

    try {
      await cleanMutation.mutateAsync(datasetId)
    } catch (error) {
      console.error('Error during cleaning:', error)
    }
  }

  if (analyzeStatus !== 'success') {
    return null
  }

  return (
    <Button
      disabled={isAnyProcessing}
      variant="outline"
      className="flex-1"
      onClick={handleClean}
    >
      {cleanStatus === 'pending' ? (
        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
      ) : (
        <span>Clean</span>
      )}
    </Button>
  )
}
