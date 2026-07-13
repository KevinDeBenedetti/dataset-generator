'use client'

import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type { LangfuseDataset } from '@/api/sdk'

interface LangfuseDatasetTableProps {
  datasets: LangfuseDataset[]
}

function formatDate(value?: string | null): string {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString()
}

export function LangfuseDatasetTable({ datasets }: LangfuseDatasetTableProps) {
  return (
    <div className="border rounded-lg overflow-x-auto">
      <Table className="w-full">
        <TableCaption>{datasets.length} dataset(s) in Langfuse</TableCaption>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Description</TableHead>
            <TableHead className="text-center">Items</TableHead>
            <TableHead className="text-center">Version</TableHead>
            <TableHead className="text-center">Created</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {datasets.map((dataset) => (
            <TableRow key={dataset.id}>
              <TableCell className="font-medium">{dataset.name}</TableCell>
              <TableCell className="text-muted-foreground">{dataset.description || '—'}</TableCell>
              <TableCell className="text-center">{dataset.item_count ?? '—'}</TableCell>
              <TableCell className="text-center">
                {dataset.version != null ? `v${dataset.version}` : '—'}
              </TableCell>
              <TableCell className="text-center">{formatDate(dataset.created_at)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
