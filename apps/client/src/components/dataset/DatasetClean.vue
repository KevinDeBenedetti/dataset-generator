<script setup lang="ts">
import { defineProps } from 'vue'
const props = defineProps<{
  cleaningResult: {
    dataset: string
    total_records: number
    removed_records: number
    threshold: number
  }
}>()
</script>

<template>
  <h3 class="text-lg font-semibold mb-2">Cleaning completed</h3>
  <div class="bg-green-50 p-4 rounded-lg">
    <p><strong>Dataset:</strong> {{ props.cleaningResult.dataset }}</p>
    <p><strong>Total records:</strong> {{ props.cleaningResult.total_records }}</p>
    <p>
      <strong>Removed records:</strong>
      {{ props.cleaningResult.removed_records }}
    </p>
    <p><strong>Threshold:</strong> {{ props.cleaningResult.threshold }}</p>
  </div>
</template>
