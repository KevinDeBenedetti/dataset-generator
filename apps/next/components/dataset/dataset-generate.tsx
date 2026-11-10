'use client'

import { useState } from 'react'
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
import { HF_REPO_PATTERN, defaultTargetRepo } from '@/components/github/recipe-state'
import { useGenerateDataset, useHubDatasets } from '@/hooks'

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
  // Pre-fills the Hugging Face dataset the draft publishes to (the "add data"
  // flow of a dataset page). Still editable — it only seeds the field.
  initialTarget?: string
}

export function DatasetGenerate({ initialTarget = '' }: DatasetGenerateProps) {
  const [source, setSource] = useState<SourceKind>('file')
  const [file, setFile] = useState<File | null>(null)
  const [url, setUrl] = useState('')
  const [title, setTitle] = useState('')
  const [target, setTarget] = useState<string | null>(initialTarget || null)
  const [targetLanguage, setTargetLanguage] = useState<string>('fr')
  const [similarityThreshold, setSimilarityThreshold] = useState([0.85])
  // '' = your LLM, set on the Models page.
  const [model, setModel] = useState('')

  const hub = useHubDatasets()
  const generateMutation = useGenerateDataset()

  const generationStatus = useGenerateStore((state) => state.generationStatus)
  const error = useGenerateStore((state) => state.error)

  // The draft publishes to an existing Hub dataset or a new one; until the
  // field is edited it follows the title (`<namespace>/<slug>`).
  const targetRepo = target ?? defaultTargetRepo(title || 'my-dataset', hub.data?.namespace)
  const targetValid = HF_REPO_PATTERN.test(targetRepo)
  const datasetName = title.trim() || targetRepo.split('/').pop() || ''

  const isProcessing = generationStatus === 'pending'

  // Whether the current source has the input it needs to run.
  const hasSource = source === 'file' ? !!file : /^https?:\/\/\S+$/i.test(url.trim())

  const handleGenerate = async () => {
    if (!hasSource || !datasetName || !targetValid) {
      return
    }

    const common = {
      name: datasetName,
      targetRepo,
      targetLanguage,
      similarityThreshold: similarityThreshold[0] ?? 0.85,
      model: model || null,
    }

    try {
      await generateMutation.mutateAsync(
        source === 'file'
          ? { ...common, source: 'file', file: file as File }
          : { ...common, source: 'url', url: url.trim() },
      )
      toast.success('Draft ready: review it before it goes to Hugging Face')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <div className="w-full flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <label className="text-sm font-medium" htmlFor="gen-title">
          Title
        </label>
        <Input
          id="gen-title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Product documentation"
          disabled={isProcessing}
        />
        <label className="text-sm font-medium" htmlFor="gen-target">
          Publishes to (Hugging Face dataset)
        </label>
        <Input
          id="gen-target"
          className="font-mono"
          list="gen-target-options"
          value={targetRepo}
          onChange={(e) => setTarget(e.target.value)}
          aria-invalid={!targetValid}
          disabled={isProcessing}
        />
        <datalist id="gen-target-options">
          {(hub.data?.datasets ?? []).map((d) => (
            <option key={d.id} value={d.id}>
              {d.pretty_name ?? d.id}
            </option>
          ))}
        </datalist>
        <p className="text-xs text-muted-foreground">
          The pairs become a draft you review before they are added to this dataset (created private
          if it doesn't exist).
        </p>

        {/* Source picker: File / Web page */}
        <div className="grid grid-cols-2 gap-1 rounded-lg bg-gray-100 p-1">
          {sourceOptions.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => setSource(opt.value)}
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
              PDF or image — each page is transcribed by the model, then mined for Q&amp;A.
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
            <div className="flex flex-col gap-1">
              <label htmlFor="model" className="text-xs text-gray-500">
                Model
              </label>
              <ModelSelect
                id="model"
                value={model}
                onChange={setModel}
                disabled={isProcessing}
                className={SELECT_CLASS}
              />
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
          </div>
        </div>

        <Button
          disabled={!hasSource || !datasetName || !targetValid || isProcessing}
          className="mt-2"
          onClick={handleGenerate}
        >
          {isProcessing ? (
            <Loader2 className="w-4 h-4 mr-2 animate-spin" />
          ) : (
            <span>Generate draft</span>
          )}
        </Button>

        {generationStatus === 'error' && <div className="text-red-500 text-sm">{error}</div>}
      </div>
    </div>
  )
}
