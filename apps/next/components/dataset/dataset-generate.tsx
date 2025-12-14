'use client'

import { useState, useMemo, useEffect } from 'react'
import { toast } from 'sonner'
import { Loader2 } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Slider } from '@/components/ui/slider'
import { DatasetGenerateAnalyse } from './dataset-generate-analyse'
import { DatasetGenerateClean } from './dataset-generate-clean'
import { useGenerateStore } from '@/stores/generate'
import { useDatasetStore } from '@/stores/dataset'
import {
  useDatasets,
  useGenerateDataset,
  useAnalyzeDataset,
  useCleanDataset,
} from '@/hooks'

const availableLanguages = [
  { value: 'fr', label: 'French' },
  { value: 'en', label: 'English' },
  { value: 'es', label: 'Spanish' },
  { value: 'de', label: 'German' },
]

export function DatasetGenerate() {
  const [url, setUrl] = useState('')
  const [datasetName, setDatasetName] = useState('')
  const [selectedDatasetId, setSelectedDatasetId] = useState<string | null>(null)
  const [targetLanguage, setTargetLanguage] = useState<string>('fr')
  const [similarityThreshold, setSimilarityThreshold] = useState([0.9])

  const { data: datasets = [] } = useDatasets()
  const generateMutation = useGenerateDataset()
  const analyzeMutation = useAnalyzeDataset()
  const cleanMutation = useCleanDataset()

  const generationStatus = useGenerateStore((state) => state.generationStatus)
  const dataset = useGenerateStore((state) => state.dataset)
  const error = useGenerateStore((state) => state.error)
  const analyzeStatus = useDatasetStore((state) => state.analyzeStatus)
  const cleanStatus = useDatasetStore((state) => state.cleanStatus)

  // Sync select with input
  useEffect(() => {
    if (selectedDatasetId) {
      const found = datasets.find((d) => d.id === selectedDatasetId)
      if (found) {
        setDatasetName(found.name)
      }
    }
  }, [selectedDatasetId, datasets])

  // Show analyze/clean when an existing dataset is selected or when the entered name matches one
  const showActions = useMemo(() => {
    return (
      selectedDatasetId !== null ||
      datasets.some((d) => d.name === datasetName) ||
      !!dataset
    )
  }, [selectedDatasetId, datasets, datasetName, dataset])

  const isAnyProcessing =
    generationStatus === 'pending' ||
    analyzeStatus === 'pending' ||
    cleanStatus === 'pending'

  const handleGenerate = async () => {
    if (!url || !datasetName) {
      return
    }

    try {
      const result = await generateMutation.mutateAsync({
        url,
        name: datasetName,
        targetLanguage,
        similarityThreshold: similarityThreshold[0] ?? 0.9,
      })

      // Only call analyze/clean with a definite string id
      const id = selectedDatasetId ?? result?.id
      if (id) {
        await analyzeMutation.mutateAsync(id)
        toast.success('Dataset analyzed successfully!')
        await cleanMutation.mutateAsync(id)
        toast.success('Dataset cleaned successfully!')
      }
    } catch (err) {
      toast.error('Error during dataset generation')
      toast.error(err instanceof Error ? err.message : String(err))
    }
  }

  const handleDatasetSelect = (value: string) => {
    if (value === 'none') {
      setSelectedDatasetId(null)
      return
    }
    setSelectedDatasetId(value)
  }

  return (
    <div className="w-full flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        {/* Select for existing dataset */}
        <Select
          value={selectedDatasetId || 'none'}
          onValueChange={handleDatasetSelect}
          disabled={isAnyProcessing}
        >
          <SelectTrigger className="w-full">
            <SelectValue placeholder="Select an existing dataset" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="none">Select an existing dataset</SelectItem>
            {datasets.map((d) => (
              <SelectItem key={d.id} value={d.id}>
                {d.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Input
          value={datasetName}
          onChange={(e) => setDatasetName(e.target.value)}
          placeholder="Dataset name"
          disabled={isAnyProcessing}
        />

        <Input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="URL"
          disabled={isAnyProcessing}
        />

        {/* Advanced options */}
        <div className="bg-gray-50 p-3 rounded-lg mt-2">
          <h4 className="text-sm font-medium mb-2">Advanced options</h4>

          <div className="space-y-3">
            <div className="flex flex-col gap-1">
              <label className="text-xs text-gray-500">Target Language</label>
              <Select value={targetLanguage} onValueChange={setTargetLanguage}>
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="Select a language" />
                </SelectTrigger>
                <SelectContent>
                  {availableLanguages.map((lang) => (
                    <SelectItem key={lang.value} value={lang.value}>
                      {lang.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="flex flex-col gap-1">
              <div className="flex justify-between">
                <label className="text-xs text-gray-500">Similarity Threshold</label>
                <span className="text-xs">{similarityThreshold[0]}</span>
              </div>
              <Slider
                value={similarityThreshold}
                onValueChange={setSimilarityThreshold}
                min={0.1}
                max={1}
                step={0.05}
              />
            </div>
          </div>
        </div>

        <div className="flex gap-2 mt-2">
          <Button
            disabled={!url || !datasetName || isAnyProcessing}
            className="flex-1"
            onClick={handleGenerate}
          >
            {generationStatus === 'pending' ? (
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            ) : (
              <span>Generate Dataset</span>
            )}
          </Button>

          {showActions && <DatasetGenerateAnalyse />}
          {showActions && <DatasetGenerateClean />}
        </div>

        {(generationStatus === 'error' ||
          analyzeStatus === 'error' ||
          cleanStatus === 'error') && (
          <div className="text-red-500 text-sm">{error}</div>
        )}
      </div>
    </div>
  )
}
