'use client'

import { useState } from 'react'
import {
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion'
import { truncateText } from '@/lib/text-utils'
import type { QaItem } from '@/api/types'

interface QAItemProps {
  qa: QaItem
  index: number
  value: string
}

export function QAItem({ qa, index, value }: QAItemProps) {
  const [expanded, setExpanded] = useState(false)

  const toggleContextExpansion = () => {
    setExpanded(!expanded)
  }

  return (
    <AccordionItem value={value} className="border border-gray-200 rounded-lg overflow-hidden">
      <AccordionTrigger className="px-4 py-3 hover:bg-gray-50 text-left">
        <div className="flex-1 space-y-2">
          <div className="font-medium text-gray-900">
            Q{index + 1}: {truncateText(qa.question, 80)}
          </div>

          <div className="flex flex-wrap gap-3 text-xs text-gray-500">
            {qa.confidence && (
              <span className="bg-blue-100 px-2 py-1 rounded">
                Confidence: {(qa.confidence * 100).toFixed(1)}%
              </span>
            )}
            <span className="bg-gray-100 px-2 py-1 rounded">
              ID: {qa.id.substring(0, 8)}...
            </span>
            {qa.created_at && (
              <span className="bg-green-100 px-2 py-1 rounded">
                {new Date(qa.created_at).toLocaleDateString('en-US')}
              </span>
            )}
          </div>
        </div>
      </AccordionTrigger>

      <AccordionContent className="px-4 pb-4">
        <div className="space-y-4">
          <div className="bg-blue-50 p-3 rounded-lg">
            <h4 className="font-medium text-blue-900 mb-2 flex items-center">
              <span className="w-2 h-2 bg-blue-500 rounded-full mr-2" />
              Question
            </h4>
            <p className="text-blue-800">{qa.question}</p>
          </div>

          <div className="bg-green-50 p-3 rounded-lg">
            <h4 className="font-medium text-green-900 mb-2 flex items-center">
              <span className="w-2 h-2 bg-green-500 rounded-full mr-2" />
              Answer
            </h4>
            <p className="text-green-800">{qa.answer}</p>
          </div>

          {qa.context && (
            <div className="bg-gray-50 p-3 rounded-lg">
              <h4 className="font-medium text-gray-900 mb-2 flex items-center">
                <span className="w-2 h-2 bg-gray-500 rounded-full mr-2" />
                Context
              </h4>
              <div className="relative">
                <p
                  className={`text-gray-700 text-sm leading-relaxed whitespace-pre-wrap ${
                    !expanded && qa.context.length > 300 ? 'max-h-32 overflow-hidden' : ''
                  }`}
                >
                  {qa.context}
                </p>

                {qa.context.length > 300 && (
                  <div
                    className={`${
                      !expanded
                        ? 'absolute bottom-0 left-0 right-0 h-8 bg-gradient-to-t from-gray-50 to-transparent'
                        : ''
                    } flex items-end justify-center`}
                  >
                    <button
                      className="text-xs bg-white border border-gray-300 px-2 py-1 rounded hover:bg-gray-100"
                      onClick={toggleContextExpansion}
                    >
                      {expanded ? 'Show less' : 'Show more'}
                    </button>
                  </div>
                )}
              </div>
            </div>
          )}

          <div className="bg-yellow-50 p-3 rounded-lg">
            <h4 className="font-medium text-yellow-900 mb-2 flex items-center">
              <span className="w-2 h-2 bg-yellow-500 rounded-full mr-2" />
              Additional Information
            </h4>
            <div className="space-y-2 text-sm">
              {qa.source_url && (
                <div className="flex items-start gap-2">
                  <span className="font-medium text-yellow-800 min-w-0">Source:</span>
                  <a
                    href={qa.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-600 hover:underline break-all"
                  >
                    {qa.source_url}
                  </a>
                </div>
              )}
              <div className="flex gap-2">
                <span className="font-medium text-yellow-800">Full ID:</span>
                <span className="font-mono text-xs bg-white px-2 py-1 rounded border">
                  {qa.id}
                </span>
              </div>
              {qa.metadata && (
                <div className="flex gap-2">
                  <span className="font-medium text-yellow-800">Metadata:</span>
                  <pre className="text-xs bg-white p-2 rounded border overflow-x-auto">
                    {JSON.stringify(qa.metadata, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          </div>
        </div>
      </AccordionContent>
    </AccordionItem>
  )
}
