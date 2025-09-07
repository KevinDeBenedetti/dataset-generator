<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { useQAStore } from '@/stores/qa'
import QAList from './QAList.vue'

interface Dataset {
  id: string
  name: string
  description: string
}

interface Props {
  dataset: Dataset
}

defineProps<Props>()

const qaStore = useQAStore()
const { qaItems, state } = storeToRefs(qaStore)
</script>

<template>
  <div class="bg-white rounded-lg shadow p-6">
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
  </div>
</template>
