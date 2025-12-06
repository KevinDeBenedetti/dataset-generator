<script setup lang="ts">
import { onMounted, computed, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { Loader2 } from 'lucide-vue-next'
import PaginationWrapper from '@/components/dataset/PaginationWrapper.vue'
import { useQAStore } from '@/stores/qa'
import QAList from './QAList.vue'
import type { DatasetResponse } from '@/api/types.gen'

const props = defineProps<{
  dataset: DatasetResponse | null
}>()

const qaStore = useQAStore()
const { qaItems, qaResponse } = storeToRefs(qaStore)

const currentPage = computed(
  () => Math.floor((qaResponse.value?.offset || 0) / (qaResponse.value?.limit || 1)) + 1
)
const totalPages = computed(() =>
  Math.ceil((qaResponse.value?.total_count || 0) / (qaResponse.value?.limit || 1))
)

const handlePageChange = async (page: number) => {
  await qaStore.goToPage(page)
}

onMounted(async () => {
  if (props.dataset?.id) {
    await qaStore.fetchQAByDataset(props.dataset.id)
  }
})

watch(
  () => props.dataset?.id,
  async (newDatasetId) => {
    if (newDatasetId) {
      await qaStore.fetchQAByDataset(newDatasetId)
    }
  }
)
</script>

<template>
  <div class="bg-white rounded-lg shadow p-6">
    <div v-if="!dataset" class="flex items-center justify-center py-8">
      <Loader2 class="h-6 w-6 animate-spin text-gray-500" />
      <span class="ml-2 text-gray-500">Loading dataset...</span>
    </div>

    <template v-else>
      <div class="mb-6">
        <h2 class="text-xl font-semibold mb-2">{{ dataset.name }}</h2>
        <p class="text-gray-600 mb-4 break-words whitespace-pre-wrap">{{ dataset.description }}</p>

        <div class="bg-gray-50 p-4 rounded-lg">
          <div class="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
            <div>
              <span class="font-medium">Total Q&A:</span>
              <span class="ml-2">{{ qaResponse?.total_count ?? '-' }}</span>
            </div>
            <div>
              <span class="font-medium">Displayed:</span>
              <span class="ml-2">{{ qaResponse?.returned_count ?? '-' }}</span>
            </div>
            <div>
              <span class="font-medium">Dataset ID:</span>
              <span class="ml-2 text-xs text-gray-600">{{ qaResponse?.dataset_id ?? '-' }}</span>
            </div>
          </div>
        </div>
      </div>

      <QAList :qa-data="qaItems" :returned-count="qaResponse?.returned_count ?? 0" />

      <PaginationWrapper
        v-if="totalPages > 1"
        class="mt-6"
        :total="qaResponse?.total_count ?? 0"
        :current-page="currentPage"
        :items-per-page="qaResponse?.limit ?? 1"
        @page-change="handlePageChange"
      />
    </template>
  </div>
</template>
