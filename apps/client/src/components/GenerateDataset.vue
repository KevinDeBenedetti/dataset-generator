<script setup lang="ts">
import { computed, ref } from 'vue'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Loader2 } from 'lucide-vue-next'

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

const handleAnalyze = async () => {
  try {
    await datasetStore.analyzeDataset()
  } catch (error) {
    console.error("Erreur lors de l'analyse:", error)
  }
}

const handleClean = async () => {
  try {
    await datasetStore.cleanDataset()
  } catch (error) {
    console.error('Erreur lors du nettoyage:', error)
  }
}

const isAnyProcessing = computed(
  () =>
    datasetStore.generationStatus === 'pending' ||
    datasetStore.analyzeStatus === 'pending' ||
    datasetStore.cleanStatus === 'pending',
)
</script>

<template>
  <div class="flex flex-col gap-6">
    <div class="flex flex-col gap-2">
      <Input v-model="url" placeholder="URL" :disabled="isAnyProcessing" />
      <Input v-model="datasetName" placeholder="Dataset Name" :disabled="isAnyProcessing" />

      <div class="flex gap-2">
        <Button
          @click="handleGenerate"
          :disabled="!url || !datasetName || isAnyProcessing"
          class="flex-1"
        >
          <Loader2
            v-if="datasetStore.generationStatus === 'pending'"
            class="w-4 h-4 mr-2 animate-spin"
          />
          <span v-else>Generate Dataset</span>
        </Button>

        <Button
          v-if="datasetStore.generationStatus === 'success'"
          @click="handleAnalyze"
          :disabled="isAnyProcessing"
          variant="outline"
          class="flex-1"
        >
          <Loader2
            v-if="datasetStore.analyzeStatus === 'pending'"
            class="w-4 h-4 mr-2 animate-spin"
          />
          <span v-else>Analyze</span>
        </Button>

        <Button
          v-if="datasetStore.analyzeStatus === 'success'"
          @click="handleClean"
          :disabled="isAnyProcessing"
          variant="outline"
          class="flex-1"
        >
          <Loader2
            v-if="datasetStore.cleanStatus === 'pending'"
            class="w-4 h-4 mr-2 animate-spin"
          />
          <span v-else>Clean</span>
        </Button>
      </div>

      <div
        v-if="
          datasetStore.generationStatus === 'error' ||
          datasetStore.analyzeStatus === 'error' ||
          datasetStore.cleanStatus === 'error'
        "
        class="text-red-500 text-sm"
      >
        {{ datasetStore.errorMessage }}
      </div>
    </div>

    <!-- Affichage des résultats de génération -->
    <div v-if="datasetStore.generationStatus === 'success' && dataset">
      <h3 class="text-lg font-semibold mb-2">Dataset généré</h3>
      <DatasetResults :result="dataset" />
    </div>

    <!-- Affichage des résultats d'analyse -->
    <div v-if="datasetStore.analyzeStatus === 'success' && datasetStore.analyzeResult">
      <h3 class="text-lg font-semibold mb-2">Analyse des similarités</h3>
      <div class="bg-gray-50 p-4 rounded-lg">
        <p><strong>Dataset:</strong> {{ datasetStore.analyzeResult.dataset }}</p>
        <p><strong>Records totaux:</strong> {{ datasetStore.analyzeResult.total_records }}</p>
        <p>
          <strong>Paires similaires trouvées:</strong>
          {{ datasetStore.analyzeResult.similar_pairs_found }}
        </p>
        <p><strong>Seuil:</strong> {{ datasetStore.analyzeResult.threshold }}</p>
      </div>
    </div>

    <!-- Affichage des résultats de nettoyage -->
    <div v-if="datasetStore.cleanStatus === 'success' && datasetStore.cleanResult">
      <h3 class="text-lg font-semibold mb-2">Nettoyage terminé</h3>
      <div class="bg-green-50 p-4 rounded-lg">
        <p><strong>Dataset:</strong> {{ datasetStore.cleanResult.dataset }}</p>
        <p><strong>Records totaux:</strong> {{ datasetStore.cleanResult.total_records }}</p>
        <p><strong>Records supprimés:</strong> {{ datasetStore.cleanResult.removed_records }}</p>
        <p><strong>Seuil:</strong> {{ datasetStore.cleanResult.threshold }}</p>
      </div>
    </div>
  </div>
</template>
