<script setup lang="ts">
import { onMounted, computed, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useDatasetStore } from '@/stores/dataset'
import { useQAStore } from '@/stores/qa'
import { useRoute } from 'vue-router'
import DatasetTable from '@/components/dataset/DatasetTable.vue'
import DatasetDetail from '@/components/dataset/DatasetDetail.vue'
import LoadingState from '@/components/dataset/LoadingState.vue'
import EmptyState from '@/components/dataset/EmptyState.vue'

const route = useRoute()
const datasetStore = useDatasetStore()
const qaStore = useQAStore()

const { datasets, dataset, loading } = storeToRefs(datasetStore)

const datasetId = computed(() => (route.params.id as string) || null)
const pageTitle = computed(() => {
  if (dataset.value) {
    return dataset.value.name
  }
  return 'Datasets'
})

watch(
  datasetId,
  async (newId) => {
    try {
      if (newId) {
        await datasetStore.selectDataset(newId as string)
        await qaStore.fetchQAByDataset(newId as string)
      } else {
        await datasetStore.fetchDatasets()
      }
    } catch (err) {
      console.error('Error during watch datasetId:', err)
    }
  },
  { immediate: true }
)

onMounted(async () => {
  try {
    if (datasetId.value) {
      await datasetStore.selectDataset(datasetId.value)
      await qaStore.fetchQAByDataset(datasetId.value)
    } else {
      const response = await datasetStore.fetchDatasets()
      void response
    }
  } catch (err) {
    console.error('Error onMounted:', err)
  }
})
</script>

<template>
  <section class="max-w-2xl mx-auto flex flex-col gap-4 w-full">
    <h1 class="mt-6 mb-4 text-3xl font-bold text-center">
      {{ pageTitle }}
    </h1>

    <LoadingState v-if="loading" />

    <DatasetDetail v-if="datasetId" :dataset="dataset" />

    <DatasetTable v-else-if="datasets && datasets.length > 0" :datasets="datasets" />

    <EmptyState v-if="!loading && (!datasets || datasets.length === 0)" />
  </section>
</template>
