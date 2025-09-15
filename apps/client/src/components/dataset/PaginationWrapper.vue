<script setup lang="ts">
import { computed } from 'vue'
import {
  Pagination,
  PaginationContent,
  PaginationEllipsis,
  PaginationFirst,
  PaginationItem,
  PaginationLast,
  PaginationNext,
  PaginationPrevious,
} from '@/components/ui/pagination'

interface Props {
  total: number
  currentPage: number
  itemsPerPage: number
  disabled?: boolean
}

interface Emits {
  (e: 'page-change', page: number): void
}

const props = withDefaults(defineProps<Props>(), {
  disabled: false,
})

const emit = defineEmits<Emits>()

const totalPages = computed(() => Math.ceil(props.total / props.itemsPerPage))

const handlePageChange = (page: number) => {
  if (page === props.currentPage || props.disabled) return
  emit('page-change', page)
}

const getVisiblePages = () => {
  const pages: (number | string)[] = []
  const total = totalPages.value
  const current = props.currentPage

  if (total <= 7) {
    // Si moins de 7 pages, afficher toutes
    for (let i = 1; i <= total; i++) {
      pages.push(i)
    }
  } else {
    // Logique pour afficher les pages avec ellipses
    pages.push(1)

    if (current > 3) {
      pages.push('...')
    }

    const start = Math.max(2, current - 1)
    const end = Math.min(total - 1, current + 1)

    for (let i = start; i <= end; i++) {
      pages.push(i)
    }

    if (current < total - 2) {
      pages.push('...')
    }

    if (total > 1) {
      pages.push(total)
    }
  }

  return pages
}
</script>

<template>
  <div v-if="totalPages > 1" class="flex justify-center">
    <Pagination
      :total="total"
      :page="currentPage"
      :items-per-page="itemsPerPage"
      @page-change="handlePageChange"
    >
      <PaginationContent>
        <PaginationFirst :disabled="currentPage === 1 || disabled" @click="handlePageChange(1)" />
        <PaginationPrevious
          :disabled="currentPage === 1 || disabled"
          @click="handlePageChange(currentPage - 1)"
        />

        <!-- Pages numérotées -->
        <template v-for="page in getVisiblePages()" :key="page">
          <PaginationItem v-if="page === '...'" class="text-gray-400">
            <PaginationEllipsis />
          </PaginationItem>
          <PaginationItem v-else :value="page as number">
            <button
              :disabled="disabled"
              :class="[
                'px-3 py-2 text-sm rounded-md transition-colors',
                page === currentPage ? 'bg-blue-600 text-white' : 'text-gray-700 hover:bg-gray-100',
                disabled && 'opacity-50 cursor-not-allowed',
              ]"
              @click="handlePageChange(page as number)"
            >
              {{ page }}
            </button>
          </PaginationItem>
        </template>

        <PaginationNext
          :disabled="currentPage === totalPages || disabled"
          @click="handlePageChange(currentPage + 1)"
        />
        <PaginationLast
          :disabled="currentPage === totalPages || disabled"
          @click="handlePageChange(totalPages)"
        />
      </PaginationContent>
    </Pagination>
  </div>
</template>
