"use client";

import { useState, useMemo } from "react";
import { toast } from "sonner";
import { Loader2 } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { DatasetGenerateAnalyse } from "./dataset-generate-analyse";
import { DatasetGenerateClean } from "./dataset-generate-clean";
import { useGenerateStore } from "@/stores/generate";
import { useDatasetStore } from "@/stores/dataset";
import {
  useDatasets,
  useGenerateDataset,
  useAnalyzeDataset,
  useCleanDataset,
} from "@/hooks";

const availableLanguages = [
  { value: "fr", label: "French" },
  { value: "en", label: "English" },
  { value: "es", label: "Spanish" },
  { value: "de", label: "German" },
];

type SourceKind = "url" | "file" | "github";

const sourceOptions: { value: SourceKind; label: string }[] = [
  { value: "url", label: "URL" },
  { value: "file", label: "File" },
  { value: "github", label: "GitHub" },
];

export function DatasetGenerate() {
  const [source, setSource] = useState<SourceKind>("url");
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [githubUsername, setGithubUsername] = useState("");
  const [githubToken, setGithubToken] = useState("");
  const [maxRepos, setMaxRepos] = useState("");
  const [manualDatasetName, setManualDatasetName] = useState("");
  const [selectedDatasetId, setSelectedDatasetId] = useState<string | null>(
    null
  );
  const [targetLanguage, setTargetLanguage] = useState<string>("fr");
  const [similarityThreshold, setSimilarityThreshold] = useState([0.9]);
  const [crawl, setCrawl] = useState(true);
  const [maxDepth, setMaxDepth] = useState("2");
  const [maxPages, setMaxPages] = useState("50");
  const [syncLangfuse, setSyncLangfuse] = useState(true);

  const { data: datasets = [] } = useDatasets();
  const generateMutation = useGenerateDataset();
  const analyzeMutation = useAnalyzeDataset();
  const cleanMutation = useCleanDataset();

  const generationStatus = useGenerateStore((state) => state.generationStatus);
  const dataset = useGenerateStore((state) => state.dataset);
  const error = useGenerateStore((state) => state.error);
  const analyzeStatus = useDatasetStore((state) => state.analyzeStatus);
  const cleanStatus = useDatasetStore((state) => state.cleanStatus);

  // Derive datasetName from selected dataset or use manual input
  const datasetName = useMemo(() => {
    if (selectedDatasetId) {
      const found = datasets.find((d) => d.id === selectedDatasetId);
      return found?.name || manualDatasetName;
    }
    return manualDatasetName;
  }, [selectedDatasetId, datasets, manualDatasetName]);

  // Show analyze/clean when an existing dataset is selected or when the entered name matches one
  const showActions = useMemo(() => {
    return (
      selectedDatasetId !== null ||
      datasets.some((d) => d.name === datasetName) ||
      !!dataset
    );
  }, [selectedDatasetId, datasets, datasetName, dataset]);

  const isAnyProcessing =
    generationStatus === "pending" ||
    analyzeStatus === "pending" ||
    cleanStatus === "pending";

  // Whether the current source has the input it needs to run.
  const hasSource = useMemo(() => {
    if (source === "url") return !!url;
    if (source === "file") return !!file;
    return !!githubUsername;
  }, [source, url, file, githubUsername]);

  const handleGenerate = async () => {
    if (!hasSource || !datasetName) {
      return;
    }

    const threshold = similarityThreshold[0] ?? 0.9;

    try {
      const result = await generateMutation.mutateAsync(
        source === "file"
          ? {
              source: "file",
              file: file as File,
              name: datasetName,
              targetLanguage,
              similarityThreshold: threshold,
              syncLangfuse,
            }
          : source === "github"
            ? {
                source: "github",
                githubUsername,
                githubToken: githubToken || null,
                name: datasetName,
                targetLanguage,
                similarityThreshold: threshold,
                maxRepos: Number(maxRepos) || null,
                syncLangfuse,
              }
            : {
                source: "url",
                url,
                name: datasetName,
                targetLanguage,
                similarityThreshold: threshold,
                crawl,
                maxDepth: crawl ? Number(maxDepth) || null : null,
                maxPages: crawl ? Number(maxPages) || null : null,
                syncLangfuse,
              }
      );

      // Analyze/clean are keyed by the Langfuse dataset name (the source of
      // truth). datasetName is already the selected/entered name.
      const name = datasetName || result?.dataset_name;
      if (name) {
        await analyzeMutation.mutateAsync(name);
        toast.success("Dataset analyzed successfully!");
        await cleanMutation.mutateAsync(name);
        toast.success("Dataset cleaned successfully!");
      }
    } catch (err) {
      toast.error("Error during dataset generation");
      toast.error(err instanceof Error ? err.message : String(err));
    }
  };

  const handleDatasetSelect = (value: string) => {
    if (value === "none") {
      setSelectedDatasetId(null);
      return;
    }
    setSelectedDatasetId(value);
  };

  return (
    <div className="w-full flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        {/* Select for existing dataset */}
        <Select
          value={selectedDatasetId || "none"}
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
          onChange={(e) => setManualDatasetName(e.target.value)}
          placeholder="Dataset name"
          disabled={isAnyProcessing}
        />

        {/* Source picker: URL / File / GitHub */}
        <div className="grid grid-cols-3 gap-1 rounded-lg bg-gray-100 p-1">
          {sourceOptions.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => setSource(opt.value)}
              disabled={isAnyProcessing}
              className={`rounded-md py-1.5 text-sm font-medium transition-colors ${
                source === opt.value
                  ? "bg-white shadow-sm text-gray-900"
                  : "text-gray-500 hover:text-gray-700"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>

        {source === "url" && (
          <Input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="URL"
            disabled={isAnyProcessing}
          />
        )}

        {source === "file" && (
          <div className="flex flex-col gap-1">
            <input
              type="file"
              accept=".pdf,image/*"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              disabled={isAnyProcessing}
              className="text-sm file:mr-2 file:rounded-md file:border-0 file:bg-primary file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-primary-foreground"
            />
            <span className="text-xs text-gray-400">
              PDF or image — each page is transcribed with the vision model.
            </span>
          </div>
        )}

        {source === "github" && (
          <div className="flex flex-col gap-2">
            <Input
              value={githubUsername}
              onChange={(e) => setGithubUsername(e.target.value)}
              placeholder="GitHub username"
              disabled={isAnyProcessing}
            />
            <Input
              type="password"
              value={githubToken}
              onChange={(e) => setGithubToken(e.target.value)}
              placeholder="GitHub token (optional — raises the API rate limit)"
              disabled={isAnyProcessing}
            />
            <span className="text-xs text-gray-400">
              Public repos only. README + top-level docs are mined.
            </span>
          </div>
        )}

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
                <label className="text-xs text-gray-500">
                  Similarity Threshold
                </label>
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

            {/* Crawl the whole site (URL source only) */}
            {source === "url" && (
              <div className="flex flex-col gap-2 border-t pt-3">
                <label className="flex items-center gap-2 text-xs text-gray-700">
                  <input
                    type="checkbox"
                    className="size-4 accent-primary"
                    checked={crawl}
                    onChange={(e) => setCrawl(e.target.checked)}
                    disabled={isAnyProcessing}
                  />
                  <span className="font-medium">Crawl entire site</span>
                  <span className="text-gray-400">
                    (follow same-domain links)
                  </span>
                </label>

                {crawl && (
                  <div className="grid grid-cols-2 gap-2 pl-6">
                    <div className="flex flex-col gap-1">
                      <label className="text-xs text-gray-500">Max depth</label>
                      <Input
                        type="number"
                        min={0}
                        value={maxDepth}
                        onChange={(e) => setMaxDepth(e.target.value)}
                        disabled={isAnyProcessing}
                      />
                    </div>
                    <div className="flex flex-col gap-1">
                      <label className="text-xs text-gray-500">Max pages</label>
                      <Input
                        type="number"
                        min={1}
                        value={maxPages}
                        onChange={(e) => setMaxPages(e.target.value)}
                        disabled={isAnyProcessing}
                      />
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Max repos (GitHub source only) */}
            {source === "github" && (
              <div className="flex flex-col gap-1 border-t pt-3">
                <label className="text-xs text-gray-500">
                  Max repos (optional)
                </label>
                <Input
                  type="number"
                  min={1}
                  value={maxRepos}
                  onChange={(e) => setMaxRepos(e.target.value)}
                  placeholder="all public repos"
                  disabled={isAnyProcessing}
                />
              </div>
            )}

            {/* Langfuse versioning */}
            <div className="flex flex-col gap-1 border-t pt-3">
              <label className="flex items-center gap-2 text-xs text-gray-700">
                <input
                  type="checkbox"
                  className="size-4 accent-primary"
                  checked={syncLangfuse}
                  onChange={(e) => setSyncLangfuse(e.target.checked)}
                  disabled={isAnyProcessing}
                />
                <span className="font-medium">Version to Langfuse</span>
                <span className="text-gray-400">
                  (create & version dataset)
                </span>
              </label>
            </div>
          </div>
        </div>

        <div className="flex gap-2 mt-2">
          <Button
            disabled={!hasSource || !datasetName || isAnyProcessing}
            className="flex-1"
            onClick={handleGenerate}
          >
            {generationStatus === "pending" ? (
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            ) : (
              <span>Generate Dataset</span>
            )}
          </Button>

          {showActions && <DatasetGenerateAnalyse />}
          {showActions && <DatasetGenerateClean />}
        </div>

        {(generationStatus === "error" ||
          analyzeStatus === "error" ||
          cleanStatus === "error") && (
          <div className="text-red-500 text-sm">{error}</div>
        )}
      </div>
    </div>
  );
}
