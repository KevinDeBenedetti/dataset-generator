'use client'

import { useMemo } from 'react'
import { cn } from '@/lib/utils'
import {
  ChevronFirst,
  ChevronLast,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react'
import { Button } from '@/components/ui/button'

interface PaginationWrapperProps {
  total: number
  currentPage: number
  itemsPerPage: number
  disabled?: boolean
  onPageChange: (page: number) => void
  className?: string
}

export function PaginationWrapper({
  total,
  currentPage,
  itemsPerPage,
  disabled = false,
  onPageChange,
  className,
}: PaginationWrapperProps) {
  const totalPages = Math.ceil(total / itemsPerPage)

  const handlePageChange = (page: number) => {
    if (page === currentPage || disabled) return
    onPageChange(page)
  }

  const visiblePages = useMemo(() => {
    const pages: (number | string)[] = []

    if (totalPages <= 7) {
      for (let i = 1; i <= totalPages; i++) {
        pages.push(i)
      }
    } else {
      pages.push(1)

      if (currentPage > 3) {
        pages.push('...')
      }

      const start = Math.max(2, currentPage - 1)
      const end = Math.min(totalPages - 1, currentPage + 1)

      for (let i = start; i <= end; i++) {
        pages.push(i)
      }

      if (currentPage < totalPages - 2) {
        pages.push('...')
      }

      if (totalPages > 1) {
        pages.push(totalPages)
      }
    }

    return pages
  }, [totalPages, currentPage])

  if (totalPages <= 1) {
    return null
  }

  return (
    <div className={cn('flex justify-center items-center gap-1', className)}>
      <Button
        variant="outline"
        size="icon"
        disabled={currentPage === 1 || disabled}
        onClick={() => handlePageChange(1)}
      >
        <ChevronFirst className="h-4 w-4" />
      </Button>

      <Button
        variant="outline"
        size="icon"
        disabled={currentPage === 1 || disabled}
        onClick={() => handlePageChange(currentPage - 1)}
      >
        <ChevronLeft className="h-4 w-4" />
      </Button>

      {visiblePages.map((page, index) =>
        page === '...' ? (
          <span key={`ellipsis-${index}`} className="px-2 text-gray-400">
            ...
          </span>
        ) : (
          <button
            key={page}
            disabled={disabled}
            className={cn(
              'px-3 py-2 text-sm rounded-md transition-colors',
              page === currentPage
                ? 'bg-primary text-primary-foreground'
                : 'text-gray-700 hover:bg-gray-100',
              disabled && 'opacity-50 cursor-not-allowed'
            )}
            onClick={() => handlePageChange(page as number)}
          >
            {page}
          </button>
        )
      )}

      <Button
        variant="outline"
        size="icon"
        disabled={currentPage === totalPages || disabled}
        onClick={() => handlePageChange(currentPage + 1)}
      >
        <ChevronRight className="h-4 w-4" />
      </Button>

      <Button
        variant="outline"
        size="icon"
        disabled={currentPage === totalPages || disabled}
        onClick={() => handlePageChange(totalPages)}
      >
        <ChevronLast className="h-4 w-4" />
      </Button>
    </div>
  )
}
