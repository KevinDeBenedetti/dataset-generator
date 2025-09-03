<script setup lang="ts">
import { computed, ref } from 'vue'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Loader2 } from "lucide-vue-next"

import { useDatasetStore } from '@/stores/dataset'

import DatasetResults from './DatasetResults.vue'

const datasetStore = useDatasetStore()
const url = ref('')
const datasetName = ref('')
const dataset = computed(() => datasetStore.lastResult)

const handleGenerate = async () => {
  if (!url.value || !datasetName.value) {
    return
  }

  try {
    await datasetStore.generateDataset(url.value, datasetName.value)
  } catch (error) {
    console.error('Erreur lors de la génération:', error)
  }
}
</script>

<template>
  <div class="flex flex-col gap-6">
    <div class="flex flex-col gap-2">
      <Input
        v-model="url"
        placeholder="URL"
        :disabled="datasetStore.generationStatus === 'pending'"
      />
      <Input
        v-model="datasetName"
        placeholder="Dataset Name"
        :disabled="datasetStore.generationStatus === 'pending'"
      />
      <Button
        @click="handleGenerate"
        :disabled="!url || !datasetName || datasetStore.generationStatus === 'pending'"
      >
        <Loader2 v-if="datasetStore.generationStatus === 'pending'" class="w-4 h-4 mr-2 animate-spin" />
        <span v-else>Generate Dataset</span>
      </Button>

      <div v-if="datasetStore.generationStatus === 'error'" class="text-red-500 text-sm">
        {{ datasetStore.errorMessage }}
      </div>

    </div>

    <!-- Affichage des résultats -->
    <div v-if="datasetStore.generationStatus === 'success' && dataset">
      <DatasetResults :result="dataset" />
    </div>
  </div>
</template>
