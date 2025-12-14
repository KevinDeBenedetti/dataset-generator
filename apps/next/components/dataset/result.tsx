'use client'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { ScrollArea } from '@/components/ui/scroll-area'
import type { DatasetGenerationResponse, DatasetResponse } from '@/api/types'

interface ResultProps {
  result: DatasetGenerationResponse | DatasetResponse | null
}

function isGenerationResponse(
  result: DatasetGenerationResponse | DatasetResponse
): result is DatasetGenerationResponse {
  return 'qa_pairs' in result
}

export function Result({ result }: ResultProps) {
  if (!result) {
    return <div className="text-gray-500">No results available</div>
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
            <Badge variant="secondary">Model: {result.model_qa}</Badge>
            <Badge variant="secondary">Threshold: {result.similarity_threshold}</Badge>
            <Badge variant="secondary">Language: {result.target_language}</Badge>
          </div>
        </CardDescription>
      </CardHeader>

      <CardContent>
        <div className="mb-4 flex flex-wrap gap-6">
          <div>
            <strong>Total questions:</strong> {result.total_questions}
          </div>
          <div>
            <strong>Processing time:</strong> {result.processing_time.toFixed(2)}s
          </div>
        </div>

        <Separator className="my-2" />

        <h4 className="font-semibold mb-2">Q&A Pairs</h4>
        <ScrollArea className="h-64">
          <div className="space-y-3 p-2">
            {result.qa_pairs.map((pair, index) => (
              <div
                key={index}
                className="p-3 border border-gray-200 rounded-md bg-white"
              >
                <p className="font-medium">Q: {pair.question}</p>
                <p className="mt-1 text-gray-700">A: {pair.answer}</p>
              </div>
            ))}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  )
}
