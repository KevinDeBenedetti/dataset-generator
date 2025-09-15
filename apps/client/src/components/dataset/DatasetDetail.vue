<script setup lang="ts">
import { onMounted, computed, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { Loader2 } from 'lucide-vue-next'
import PaginationWrapper from '@/components/dataset/PaginationWrapper.vue'
import { useQAStore } from '@/stores/qa'
import QAList from './QAList.vue'

interface Dataset {
  id: string
  name: string
  description: string
}

interface Props {
  dataset: Dataset | null
}

const props = defineProps<Props>()

const qaStore = useQAStore()
const { qaItems, state } = storeToRefs(qaStore)

// Computed pour la pagination
const currentPage = computed(() => Math.floor(state.value.offset / state.value.limit) + 1)
const totalPages = computed(() => Math.ceil(state.value.totalCount / state.value.limit))

const handlePageChange = async (page: number) => {
  await qaStore.goToPage(page)
}

onMounted(async () => {
  if (props.dataset?.id) {
    console.log('Fetching QA items for dataset:', props.dataset.id)
    await qaStore.fetchQAByDataset(props.dataset.id)
  }
})

// Watcher pour réagir aux changements de dataset
watch(
  () => props.dataset?.id,
  async (newDatasetId) => {
    if (newDatasetId) {
      qaStore.clearData()
      await qaStore.fetchQAByDataset(newDatasetId)
    }
  }
)
</script>

<template>
  <div class="bg-white rounded-lg shadow p-6">
    <div v-if="!dataset" class="flex items-center justify-center py-8">
      <Loader2 class="h-6 w-6 animate-spin text-gray-500" />
      <span class="ml-2 text-gray-500">Chargement du dataset...</span>
    </div>

    <template v-else>
      <div class="mb-6">
        <h2 class="text-xl font-semibold mb-2">{{ dataset.name }}</h2>
        <p class="text-gray-600 mb-4 break-words whitespace-pre-wrap">{{ dataset.description }}</p>

        <div class="bg-gray-50 p-4 rounded-lg">
          <div class="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
            <div>
              <span class="font-medium">Total Q&A:</span>
              <span class="ml-2">{{ state.totalCount ?? '-' }}</span>
            </div>
            <div>
              <span class="font-medium">Affichées:</span>
              <span class="ml-2">{{ state.returnedCount ?? '-' }}</span>
            </div>
            <div>
              <span class="font-medium">Dataset ID:</span>
              <span class="ml-2 text-xs text-gray-600">{{ state.datasetId ?? '-' }}</span>
            </div>
          </div>
        </div>
      </div>

      <QAList :qa-data="qaItems" :returned-count="state.returnedCount" />

      <!-- Pagination -->
      <PaginationWrapper
        v-if="totalPages > 1"
        class="mt-6"
        :total="state.totalCount"
        :current-page="currentPage"
        :items-per-page="state.limit"
        @page-change="handlePageChange"
      />
    </template>
  </div>
</template>
