<script setup lang="ts">
import { computed } from 'vue'

import GenerateDataset from '@/components/dataset/DatasetGenerate.vue'
import DatasetResults from '@/components/dataset/Result.vue'
import DatasetAnalyze from '@/components/dataset/DatasetAnalyze.vue'
import DatasetClean from '@/components/dataset/DatasetClean.vue'

import { useGenerateStore } from '@/stores/generate'
import { useDatasetStore } from '@/stores/dataset'

const generateStore = useGenerateStore()
const datasetStore = useDatasetStore()

const dataset = computed(() => generateStore.dataset)
const analyzingResult = computed(() => datasetStore.analyzingResult)
const cleaningResult = computed(() => datasetStore.cleaningResult)
const analyzeStatus = computed(() => generateStore.analyzeStatus)
const cleanStatus = computed(() => generateStore.cleanStatus)

// FIXME :
import type { DatasetResponse } from '@/api/types.gen.ts'
import { getdataset } from '@/api/sdk.gen.ts'

const fetchDatasets = async () => {
  try {
    const response = await getdataset()
    const raw = response?.data
    const datasets: DatasetResponse[] = Array.isArray(raw) ? raw : raw ? [raw] : []
    console.log('Fetched datasets:', datasets)
    return datasets
  } catch (error) {
    console.error('Error fetching datasets:', error)
  }
}
fetchDatasets()
</script>

<template>
  <section class="max-w-2xl mx-auto flex flex-col gap-4">
    <h1 class="w-full mt-6 mb-4 text-3xl font-bold text-center">Generate a dataset</h1>

    <GenerateDataset />

    <!-- Generated dataset display -->
    <div v-if="generateStore.generationStatus === 'success' && dataset">
      <h3 class="text-lg font-semibold mb-2">Generated Dataset</h3>
      <DatasetResults :result="dataset" />
    </div>

    <!-- Similarity analysis display -->
    <div v-if="analyzeStatus === 'success' && analyzingResult">
      <DatasetAnalyze />
    </div>

    <!-- Cleaning results display -->
    <div v-if="cleanStatus === 'success' && cleaningResult">
      <DatasetClean />
    </div>
  </section>
</template>
