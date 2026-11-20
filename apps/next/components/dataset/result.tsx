'use client'

import { useTranslations } from 'next-intl'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { ScrollArea } from '@/components/ui/scroll-area'
import type { DatasetGenerationResponse, DatasetResponse } from '@/api/types'
import { rich } from '@/lib/rich'

interface ResultProps {
  result: DatasetGenerationResponse | DatasetResponse | null
}

function isGenerationResponse(
  result: DatasetGenerationResponse | DatasetResponse,
): result is DatasetGenerationResponse {
  return 'qa_pairs' in result
}

export function Result({ result }: ResultProps) {
  const t = useTranslations('generate.result')
  if (!result) {
    return <div className="text-gray-500">{t('empty')}</div>
  }

  if (!isGenerationResponse(result)) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{result.name}</CardTitle>
          <CardDescription>{result.description}</CardDescription>
        </CardHeader>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{result.dataset_name}</CardTitle>
        <CardDescription>
          <div className="flex flex-wrap gap-2 mt-2">
            <Badge variant="secondary">{t('model', { model: result.model })}</Badge>
            <Badge variant="secondary">
              {t('threshold', { value: result.similarity_threshold })}
            </Badge>
            <Badge variant="secondary">{t('language', { language: result.target_language })}</Badge>
            {result.pages_crawled != null && (
              <Badge variant="secondary">
                {t('pagesCrawled', { count: result.pages_crawled })}
              </Badge>
            )}
            {result.persisted && (
              <Badge variant="secondary">
                {t('saved', {
                  run: String(result.persisted.run_name ?? ''),
                  count: String(result.persisted.created_count ?? 0),
                })}
              </Badge>
            )}
          </div>
        </CardDescription>
      </CardHeader>

      <CardContent>
        <div className="mb-4 flex flex-wrap gap-6">
          <div>
            {t.rich('totalQuestions', {
              count: result.total_questions,
              strong: rich.strong,
            })}
          </div>
          <div>
            {t.rich('processingTime', {
              seconds: result.processing_time.toFixed(2),
              strong: rich.strong,
            })}
          </div>
        </div>

        <Separator className="my-2" />

        <h4 className="font-semibold mb-2">{t('pairsTitle')}</h4>
        <ScrollArea className="h-64">
          <div className="space-y-3 p-2">
            {result.qa_pairs.map((pair) => (
              // QaPair has no id field; the pipeline already deduplicates by
              // similarity before pairs reach here, so the question is a
              // safe, stable key.
              <div key={pair.question} className="p-3 border border-gray-200 rounded-md bg-white">
                <p className="font-medium">{t('question', { text: pair.question })}</p>
                <p className="mt-1 text-gray-700">{t('answer', { text: pair.answer })}</p>
              </div>
            ))}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  )
}
