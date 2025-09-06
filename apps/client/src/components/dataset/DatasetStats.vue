<script setup lang="ts">
interface Props {
  totalCount: number | null
  returnedCount: number | null
  datasetId: string | null
}

defineProps<Props>()
</script>

<template>
  <div class="bg-gray-50 p-4 rounded-lg">
    <div class="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
      <div>
        <span class="font-medium">Total Q&A:</span>
        <span class="ml-2">{{ totalCount ?? '-' }}</span>
      </div>
      <div>
        <span class="font-medium">Affichées:</span>
        <span class="ml-2">{{ returnedCount ?? '-' }}</span>
      </div>
      <div>
        <span class="font-medium">Dataset ID:</span>
        <span class="ml-2 text-xs text-gray-600">{{ datasetId ?? '-' }}</span>
      </div>
    </div>
  </div>
</template>
