'use client'

import { Accordion } from '@/components/ui/accordion'
import { QAItem } from './qa-item'
import type { QaItem } from '@/api/types'

interface QAListProps {
  qaData: QaItem[]
  returnedCount: number
}

export function QAList({ qaData, returnedCount }: QAListProps) {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-medium">Questions & Answers</h3>
        <span className="text-sm text-gray-500">
          {returnedCount} question-answer pair(s) found
        </span>
      </div>

      {qaData && qaData.length > 0 ? (
        <Accordion type="single" collapsible className="space-y-2">
          {qaData.map((qa, index) => (
            <QAItem
              key={qa.id}
              qa={qa}
              index={index}
              value={`item-${index}`}
            />
          ))}
        </Accordion>
      ) : (
        <div className="text-center py-8 text-gray-500">
          No question-answer pairs found for this dataset.
        </div>
      )}
    </div>
  )
}
