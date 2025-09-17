<script setup lang="ts">
import { useDatasetStore } from '@/stores/dataset'
import { storeToRefs } from 'pinia'

const datasetStore = useDatasetStore()
const { cleaningResult } = storeToRefs(datasetStore)
</script>

<template>
  <h3 class="text-lg font-semibold mb-2">Cleaning completed</h3>
  <div class="bg-green-50 p-4 rounded-lg">
    <p><strong>Dataset:</strong> {{ cleaningResult?.dataset_id }}</p>
    <p><strong>Total records:</strong> {{ cleaningResult?.total_records }}</p>
    <p>
      <strong>Removed records:</strong>
      {{ cleaningResult?.removed_records }}
    </p>
    <p><strong>Threshold:</strong> {{ cleaningResult?.threshold }}</p>
  </div>
</template>
