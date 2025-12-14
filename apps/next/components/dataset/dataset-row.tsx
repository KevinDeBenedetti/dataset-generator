'use client'

import Link from 'next/link'
import { toast } from 'sonner'
import { TableCell, TableRow } from '@/components/ui/table'
import { Button } from '@/components/ui/button'
import { useDeleteDataset, useExportToLangfuse } from '@/hooks'
import { truncateText } from '@/lib/text-utils'

interface Dataset {
  id: string
  name: string
  description: string
}

interface DatasetRowProps {
  dataset: Dataset
}

export function DatasetRow({ dataset }: DatasetRowProps) {
  const deleteMutation = useDeleteDataset()
  const exportMutation = useExportToLangfuse()

  const handleDeleteDataset = async () => {
    if (confirm(`Are you sure you want to delete the dataset "${dataset.name}"?`)) {
      try {
        await deleteMutation.mutateAsync(dataset.id)
        toast.success('Dataset deleted successfully!')
      } catch (error) {
        console.error('Error during deletion:', error)
        toast.error('Failed to delete dataset.')
      }
    }
  }

  const handleExportDataset = async () => {
    try {
      await exportMutation.mutateAsync({ datasetName: dataset.name })
      toast.success('Dataset exported successfully!')
    } catch (error) {
      console.error('Error during export:', error)
      toast.error('Failed to export dataset.')
    }
  }

  return (
    <TableRow>
      <TableCell className="font-mono text-sm text-gray-500">
        {truncateText(dataset.id, 8)}
      </TableCell>
      <TableCell className="font-medium">{dataset.name}</TableCell>
      <TableCell className="text-sm text-gray-600">
        {truncateText(dataset.description, 20)}
      </TableCell>
      <TableCell className="text-center">
        <div className="flex gap-2 justify-center">
          <Link href={`/datasets/${dataset.id}`}>
            <Button variant="outline" size="sm" className="text-blue-600 hover:text-blue-700">
              Open
            </Button>
          </Link>
          <Button
            variant="outline"
            size="sm"
            className="text-red-600 hover:text-red-700"
            onClick={handleDeleteDataset}
            disabled={deleteMutation.isPending}
          >
            Delete
          </Button>
        </div>
      </TableCell>
      <TableCell className="font-medium">
        <Button
          variant="outline"
          size="sm"
          className="text-gray-600 hover:text-gray-700 w-full"
          onClick={handleExportDataset}
          disabled={exportMutation.isPending}
        >
          Export
        </Button>
      </TableCell>
    </TableRow>
  )
}
