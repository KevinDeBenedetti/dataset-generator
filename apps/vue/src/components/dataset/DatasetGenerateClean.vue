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

const handleClean = async () => {
  if (!datasetId.value) {
    console.error('No dataset ID available for cleaning')
    return
  }

  try {
    await datasetStore.cleanDataset(datasetId.value)
  } catch (error) {
    console.error('Error during cleaning:', error)
  }
}
</script>

<template>
  <Button
    v-if="analyzeStatus === 'success'"
    :disabled="isAnyProcessing"
    variant="outline"
    class="flex-1"
    @click="handleClean"
  >
    <Loader2 v-if="cleanStatus === 'pending'" class="w-4 h-4 mr-2 animate-spin" />
    <span v-else>Clean</span>
  </Button>
</template>
