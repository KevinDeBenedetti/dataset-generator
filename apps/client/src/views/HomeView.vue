<script setup lang="ts">
import { onMounted } from 'vue'
import { storeToRefs } from 'pinia'

import GenerateDataset from '@/components/dataset/DatasetGenerate.vue'
import DatasetResults from '@/components/dataset/Result.vue'
import DatasetAnalyze from '@/components/dataset/DatasetAnalyze.vue'
import DatasetClean from '@/components/dataset/DatasetClean.vue'

import { useGenerateStore } from '@/stores/generate'
import { useDatasetStore } from '@/stores/dataset'

const generateStore = useGenerateStore()
const datasetStore = useDatasetStore()

const { dataset } = storeToRefs(generateStore)
const { analyzeStatus, analyzingResult, cleanStatus, cleaningResult } = storeToRefs(datasetStore)

onMounted(async () => {
  try {
    await datasetStore.fetchDatasets()
  } catch (err) {
    console.error('Error fetching datasets:', err)
  }
})
</script>

<template>
  <section class="max-w-2xl mx-auto flex flex-col gap-4">
    <h1 class="w-full mt-6 mb-4 text-3xl font-bold text-center">Generate a dataset</h1>

    <GenerateDataset />

    <div v-if="generateStore.generationStatus === 'success' && dataset">
      <h3 class="text-lg font-semibold mb-2">Generated Dataset</h3>
      <DatasetResults :result="dataset" />
    </div>

    <div v-if="analyzeStatus === 'success' && analyzingResult">
      <DatasetAnalyze />
    </div>

    <div v-if="cleanStatus === 'success' && cleaningResult">
      <DatasetClean />
    </div>
  </section>
</template>
