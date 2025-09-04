<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { useDatasetStore } from '@/stores/dataset'

const datasetStore = useDatasetStore()
const { error } = storeToRefs(datasetStore)

const handleRetry = () => {
  datasetStore.resetError()
  datasetStore.fetchDatasets()
}
</script>

<template>
  <div class="text-center p-4 text-red-600 bg-red-50 rounded-lg">
    <p>{{ error }}</p>
    <button
      @click="handleRetry"
      class="mt-2 px-4 py-2 bg-red-600 text-white rounded hover:bg-red-700"
    >
      Retry
    </button>
  </div>
</template>
