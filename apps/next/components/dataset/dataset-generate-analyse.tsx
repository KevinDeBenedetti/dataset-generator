'use client'

import { Button } from '@/components/ui/button'
import { Loader2 } from 'lucide-react'
import { useGenerateStore } from '@/stores/generate'
import { useDatasetStore } from '@/stores/dataset'
import { useAnalyzeDataset } from '@/hooks'

export function DatasetGenerateAnalyse() {
  const generationStatus = useGenerateStore((state) => state.generationStatus)
  const dataset = useGenerateStore((state) => state.dataset)
  const analyzeStatus = useDatasetStore((state) => state.analyzeStatus)
  const cleanStatus = useDatasetStore((state) => state.cleanStatus)

  const analyzeMutation = useAnalyzeDataset()

  const datasetId = dataset?.id || ''

  const isAnyProcessing =
    generationStatus === 'pending' ||
    analyzeStatus === 'pending' ||
    cleanStatus === 'pending'

  const handleAnalyze = async () => {
    if (!datasetId) {
      console.error('No dataset ID available for analysis')
      return
    }

    try {
      await analyzeMutation.mutateAsync(datasetId)
    } catch (error) {
      console.error('Error during analysis:', error)
    }
  }

  if (generationStatus !== 'success') {
    return null
  }

  return (
    <Button
      disabled={isAnyProcessing}
      variant="outline"
      className="flex-1"
      onClick={handleAnalyze}
    >
      {analyzeStatus === 'pending' ? (
        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
      ) : (
        <span>Analyze</span>
      )}
    </Button>
  )
}
