<script setup lang="ts">
import { computed } from 'vue'
import { useDatasetStore } from '@/stores/dataset'

const datasetStore = useDatasetStore()

const analyzingResult = computed(() => datasetStore.analyzingResult)
</script>

<template>
  <h3 class="text-lg font-semibold mb-2">Similarity Analysis</h3>
  <div class="bg-gray-50 p-4 rounded-lg">
    <p><strong>Dataset:</strong> {{ analyzingResult.dataset }}</p>
    <p><strong>Total records:</strong> {{ analyzingResult.total_records }}</p>
    <p>
      <strong>Similar pairs found:</strong>
      {{ analyzingResult.similar_pairs_found }}
    </p>
    <p><strong>Threshold:</strong> {{ analyzingResult.threshold }}</p>
  </div>
</template>
