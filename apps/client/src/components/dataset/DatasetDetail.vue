<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { useQAStore } from '@/stores/qa'
import DatasetStats from './DatasetStats.vue'
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
      <p class="text-gray-600 mb-4">{{ dataset.description }}</p>

      <DatasetStats
        :total-count="state.totalCount"
        :returned-count="state.returnedCount"
        :dataset-id="state.datasetId"
      />
    </div>

    <QAList :qa-data="qaItems" :returned-count="state.returnedCount" />
  </div>
</template>
