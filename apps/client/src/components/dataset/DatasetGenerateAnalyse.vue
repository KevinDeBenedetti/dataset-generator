<script setup lang="ts">
import { computed } from 'vue'

import { useGenerateStore } from '@/stores/generate'
import { useDatasetStore } from '@/stores/dataset'
import { Button } from '@/components/ui/button'
import { Loader2 } from 'lucide-vue-next'

const generateStore = useGenerateStore()
const datasetStore = useDatasetStore()

const datasetId = computed(() => generateStore.dataset?.id || '')
const analyzeStatus = computed(() => datasetStore.analyzeStatus)
const cleanStatus = computed(() => datasetStore.cleanStatus)

const isAnyProcessing = computed(
  () =>
    generateStore.generationStatus === 'pending' ||
    analyzeStatus.value === 'pending' ||
    cleanStatus.value === 'pending'
)

const handleAnalyze = async () => {
  if (!datasetId.value) {
    console.error('No dataset ID available for analysis')
    return
  }

  try {
    await datasetStore.analyzeDataset(datasetId.value)
  } catch (error) {
    console.error('Error during analysis:', error)
  }
}
</script>

<template>
  <Button
    v-if="generateStore.generationStatus === 'success'"
    :disabled="isAnyProcessing"
    variant="outline"
    class="flex-1"
    @click="handleAnalyze"
  >
    <Loader2 v-if="analyzeStatus === 'pending'" class="w-4 h-4 mr-2 animate-spin" />
    <span v-else>Analyze</span>
  </Button>
</template>
