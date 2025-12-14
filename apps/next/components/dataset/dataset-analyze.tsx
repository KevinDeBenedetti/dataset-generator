'use client'

import { useDatasetStore } from '@/stores/dataset'

export function DatasetAnalyze() {
  const analyzingResult = useDatasetStore((state) => state.analyzingResult)

  if (!analyzingResult) return null

  return (
    <div>
      <h3 className="text-lg font-semibold mb-2">Similarity Analysis</h3>
      <div className="bg-gray-50 p-4 rounded-lg">
        <p>
          <strong>Dataset:</strong> {analyzingResult.dataset_id}
        </p>
        <p>
          <strong>Total records:</strong> {analyzingResult.total_records}
        </p>
        <p>
          <strong>Similar pairs found:</strong> {analyzingResult.similar_pairs_found}
        </p>
        <p>
          <strong>Threshold:</strong> {analyzingResult.threshold}
        </p>
      </div>
    </div>
  )
}
