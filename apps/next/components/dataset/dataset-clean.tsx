'use client'

import { useDatasetStore } from '@/stores/dataset'

export function DatasetClean() {
  const cleaningResult = useDatasetStore((state) => state.cleaningResult)

  if (!cleaningResult) return null

  return (
    <div>
      <h3 className="text-lg font-semibold mb-2">Cleaning completed</h3>
      <div className="bg-green-50 p-4 rounded-lg">
        <p>
          <strong>Dataset:</strong> {cleaningResult.dataset_id}
        </p>
        <p>
          <strong>Total records:</strong> {cleaningResult.total_records}
        </p>
        <p>
          <strong>Removed records:</strong> {cleaningResult.removed_records}
        </p>
        <p>
          <strong>Threshold:</strong> {cleaningResult.threshold}
        </p>
      </div>
    </div>
  )
}
