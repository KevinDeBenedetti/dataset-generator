'use client'

import Link from 'next/link'
import { useLocale, useTranslations } from 'next-intl'
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

function formatDate(value: string | null | undefined, locale: string): string {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString(locale)
}

export function DatasetsTable({ datasets }: DatasetsTableProps) {
  const t = useTranslations('generate.table')
  const locale = useLocale()
  return (
    <div className="border rounded-lg overflow-x-auto">
      <Table className="stack-table w-full">
        <TableCaption>{t('caption', { count: datasets.length })}</TableCaption>
        <TableHeader>
          <TableRow>
            <TableHead>{t('name')}</TableHead>
            <TableHead>{t('description')}</TableHead>
            <TableHead className="text-center">{t('items')}</TableHead>
            <TableHead className="text-center">{t('version')}</TableHead>
            <TableHead className="text-center">{t('created')}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {datasets.map((dataset) => (
            <TableRow key={dataset.id}>
              <TableCell className="font-medium" data-label={t('name')}>
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
                data-label={t('description')}
              >
                {dataset.description || '—'}
              </TableCell>
              <TableCell className="text-center" data-label={t('items')}>
                {dataset.qa_sources_count ?? '—'}
              </TableCell>
              <TableCell className="text-center" data-label={t('version')}>
                {dataset.version != null ? `v${dataset.version}` : '—'}
              </TableCell>
              <TableCell className="text-center" data-label={t('created')}>
                {formatDate(dataset.created_at, locale)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
