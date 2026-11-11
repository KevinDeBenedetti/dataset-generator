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
      <Table className="stack-table w-full">
        <TableCaption>{datasets.length} draft(s)</TableCaption>
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
              <TableCell className="font-medium" data-label="Name">
                {/* Drafts are keyed by name — the detail route takes that
                    name, URL-encoded. */}
                <Link
                  href={`/drafts/${encodeURIComponent(dataset.name)}`}
                  className="hover:underline"
                >
                  {dataset.name}
                </Link>
              </TableCell>
              {/* Descriptions wrap rather than stretching the table. */}
              <TableCell
                className="min-w-64 whitespace-normal text-muted-foreground"
                data-label="Description"
              >
                {dataset.description || '—'}
              </TableCell>
              <TableCell className="text-center" data-label="Items">
                {dataset.qa_sources_count ?? '—'}
              </TableCell>
              <TableCell className="text-center" data-label="Version">
                {dataset.version != null ? `v${dataset.version}` : '—'}
              </TableCell>
              <TableCell className="text-center" data-label="Created">
                {formatDate(dataset.created_at)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
