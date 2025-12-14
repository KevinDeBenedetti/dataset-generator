'use client'

import {
  Table,
  TableBody,
  TableCaption,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { DatasetRow } from './dataset-row'
import type { DatasetResponse } from '@/api/types'

interface DatasetTableProps {
  datasets: DatasetResponse[]
}

export function DatasetTable({ datasets }: DatasetTableProps) {
  return (
    <div className="border rounded-lg overflow-x-auto">
      <Table className="w-full">
        <TableCaption>List of {datasets?.length || 0} available dataset(s)</TableCaption>
        <TableHeader>
          <TableRow>
            <TableHead className="text-center">ID</TableHead>
            <TableHead className="text-center">Name</TableHead>
            <TableHead className="text-center">Description</TableHead>
            <TableHead className="text-center">Actions</TableHead>
            <TableHead className="text-center">Langfuse</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {datasets.map((dataset) => (
            <DatasetRow
              key={dataset.id}
              dataset={{ ...dataset, description: dataset.description || '' }}
            />
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
