'use client'

import { useState, useMemo } from 'react'
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
import { ModelSelect } from '@/components/app/model-select'
import { useGenerateStore } from '@/stores/generate'
import { useDatasets, useGenerateDataset } from '@/hooks'

const availableLanguages = [
  { value: 'fr', label: 'French' },
  { value: 'en', label: 'English' },
  { value: 'es', label: 'Spanish' },
  { value: 'de', label: 'German' },
]

type SourceKind = 'file' | 'url'

const sourceOptions: { value: SourceKind; label: string }[] = [
  { value: 'file', label: 'File' },
  { value: 'url', label: 'Web page' },
]

const SELECT_CLASS =
  'h-9 w-full rounded-md border bg-white px-3 text-sm outline-none focus-visible:border-ring'

interface DatasetGenerateProps {
  // Pre-selects the dataset the generated pairs land in (the "add a source to
  // an existing dataset" flow). Still editable — it only seeds the field.
  initialDatasetName?: string
}

export function DatasetGenerate({ initialDatasetName = '' }: DatasetGenerateProps) {
  const [source, setSource] = useState<SourceKind>('file')
  const [file, setFile] = useState<File | null>(null)
  const [url, setUrl] = useState('')
  const [manualDatasetName, setManualDatasetName] = useState(initialDatasetName)
  const [selectedDatasetId, setSelectedDatasetId] = useState<string | null>(null)
  const [targetLanguage, setTargetLanguage] = useState<string>('fr')
  const [similarityThreshold, setSimilarityThreshold] = useState([0.85])
  const [persist, setPersist] = useState(true)
  // '' = the role default set on the Models page.
  const [modelQa, setModelQa] = useState('')
  const [modelSource, setModelSource] = useState('')

  const { data: datasets = [] } = useDatasets()
  const generateMutation = useGenerateDataset()

  const generationStatus = useGenerateStore((state) => state.generationStatus)
  const error = useGenerateStore((state) => state.error)

  // Derive datasetName from selected dataset or use manual input
  const datasetName = useMemo(() => {
    if (selectedDatasetId) {
      const found = datasets.find((d) => d.id === selectedDatasetId)
      return found?.name || manualDatasetName
    }
    return manualDatasetName
  }, [selectedDatasetId, datasets, manualDatasetName])

  const isProcessing = generationStatus === 'pending'

  // Whether the current source has the input it needs to run.
  const hasSource = source === 'file' ? !!file : /^https?:\/\/\S+$/i.test(url.trim())

  const handleGenerate = async () => {
    if (!hasSource || !datasetName) {
      return
    }

    const common = {
      name: datasetName,
      targetLanguage,
      similarityThreshold: similarityThreshold[0] ?? 0.85,
      modelQa: modelQa || null,
      persist,
    }

    try {
      await generateMutation.mutateAsync(
        source === 'file'
          ? { ...common, source: 'file', file: file as File, modelVlm: modelSource || null }
          : { ...common, source: 'url', url: url.trim(), modelCleaning: modelSource || null },
      )
      toast.success('Dataset generated')
    } catch (err) {
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
          disabled={isProcessing}
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
          onChange={(e) => setManualDatasetName(e.target.value)}
          placeholder="Dataset name"
          disabled={isProcessing}
        />

        {/* Source picker: File / Web page */}
        <div className="grid grid-cols-2 gap-1 rounded-lg bg-gray-100 p-1">
          {sourceOptions.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => {
                setSource(opt.value)
                setModelSource('')
              }}
              disabled={isProcessing}
              className={`rounded-md py-1.5 text-sm font-medium transition-colors ${
                source === opt.value
                  ? 'bg-white shadow-sm text-gray-900'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>

        {source === 'file' && (
          <div className="flex flex-col gap-1">
            <input
              type="file"
              accept=".pdf,image/*"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              disabled={isProcessing}
              className="text-sm file:mr-2 file:rounded-md file:border-0 file:bg-primary file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-primary-foreground"
            />
            <span className="text-xs text-gray-400">
              PDF or image — each page is transcribed with the vision model.
            </span>
          </div>
        )}

        {source === 'url' && (
          <div className="flex flex-col gap-1">
            <Input
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://docs.example.com/guide"
              disabled={isProcessing}
            />
            <span className="text-xs text-gray-400">
              One public page (no crawling) — its text is cleaned, then mined for Q&amp;A.
            </span>
          </div>
        )}

        {/* Advanced options */}
        <div className="bg-gray-50 p-3 rounded-lg mt-2">
          <h4 className="text-sm font-medium mb-2">Advanced options</h4>

          <div className="space-y-3">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="flex flex-col gap-1">
                <label htmlFor="model-qa" className="text-xs text-gray-500">
                  Q&amp;A model
                </label>
                <ModelSelect
                  id="model-qa"
                  value={modelQa}
                  onChange={setModelQa}
                  modelRole="qa"
                  ariaLabel="Q&A model"
                  disabled={isProcessing}
                  className={SELECT_CLASS}
                />
              </div>
              <div className="flex flex-col gap-1">
                <label htmlFor="model-source" className="text-xs text-gray-500">
                  {source === 'file' ? 'Vision model' : 'Cleaning model'}
                </label>
                <ModelSelect
                  id="model-source"
                  value={modelSource}
                  onChange={setModelSource}
                  modelRole={source === 'file' ? 'vision' : 'cleaning'}
                  ariaLabel={source === 'file' ? 'Vision model' : 'Cleaning model'}
                  disabled={isProcessing}
                  className={SELECT_CLASS}
                />
              </div>
            </div>

            <div className="flex flex-col gap-1 border-t pt-3">
              <label htmlFor="target-language" className="text-xs text-gray-500">
                Target Language
              </label>
              <Select value={targetLanguage} onValueChange={setTargetLanguage}>
                <SelectTrigger id="target-language" className="w-full">
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
                {/* Not a <label>: Radix's Slider thumb isn't a labelable
                    element, so the accessible name is set via thumbLabel
                    (aria-label) on the thumb itself instead. */}
                <span className="text-xs text-gray-500">Similarity Threshold</span>
                <span className="text-xs">{similarityThreshold[0]}</span>
              </div>
              <Slider
                value={similarityThreshold}
                onValueChange={setSimilarityThreshold}
                min={0.1}
                max={1}
                step={0.05}
                thumbLabel="Similarity threshold"
              />
            </div>

            {/* Persistence */}
            <div className="flex flex-col gap-1 border-t pt-3">
              <label className="flex items-center gap-2 text-xs text-gray-700">
                <input
                  type="checkbox"
                  className="size-4 accent-primary"
                  checked={persist}
                  onChange={(e) => setPersist(e.target.checked)}
                  disabled={isProcessing}
                />
                <span className="font-medium">Save the dataset</span>
                <span className="text-gray-400">(store the pairs & record a version)</span>
              </label>
            </div>
          </div>
        </div>

        <Button
          disabled={!hasSource || !datasetName || isProcessing}
          className="mt-2"
          onClick={handleGenerate}
        >
          {isProcessing ? (
            <Loader2 className="w-4 h-4 mr-2 animate-spin" />
          ) : (
            <span>Generate Dataset</span>
          )}
        </Button>

        {generationStatus === 'error' && <div className="text-red-500 text-sm">{error}</div>}
      </div>
    </div>
  )
}
