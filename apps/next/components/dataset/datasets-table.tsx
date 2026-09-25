'use client'

import Link from 'next/link'
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type { DatasetResponse } from '@/api/types'

interface DatasetsTableProps {
  datasets: DatasetResponse[]
}

function formatDate(value?: string | null): string {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString()
}

export function DatasetsTable({ datasets }: DatasetsTableProps) {
  return (
    <div className="border rounded-lg overflow-x-auto">
      <Table className="w-full">
        <TableCaption>{datasets.length} dataset(s)</TableCaption>
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
              <TableCell className="font-medium">
                {/* Datasets are keyed by name — the detail route takes that
                    name, URL-encoded. */}
                <Link
                  href={`/datasets/${encodeURIComponent(dataset.name)}`}
                  className="hover:underline"
                >
                  {dataset.name}
                </Link>
              </TableCell>
              <TableCell className="text-muted-foreground">{dataset.description || '—'}</TableCell>
              <TableCell className="text-center">{dataset.qa_sources_count ?? '—'}</TableCell>
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
